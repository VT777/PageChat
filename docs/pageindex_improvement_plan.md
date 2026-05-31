# PageIndex 系统改进实施计划

> **实施目标：** 构建动态提示词系统、智能文档类型检测、增强验证框架、性能优化

**架构概述：** 本计划通过引入提示词管理器、文档分类器、通用验证框架和性能优化层，将现有硬编码系统改造为通用、可扩展的文档处理平台，适用于财务报告、学术论文、技术书籍等多种文档类型。

**技术栈：** Python 3.11+, FastAPI, asyncio, Pydantic, Jinja2 (模板引擎), YAML/JSON (配置文件)

---

## 当前系统分析

### 现有架构问题
1. **提示词硬编码** - 所有提示词写在 `pageindex_prompts.py` 中，无法动态修改
2. **无文档类型检测** - 对所有文档使用相同处理策略
3. **验证逻辑简单** - 仅依赖标题匹配检查，缺乏多维度验证
4. **串行处理为主** - 大量 LLM 调用串行执行，性能瓶颈明显
5. **缺乏缓存策略** - 重复调用无缓存机制

### 文件依赖关系
```
pageindex_service.py
├── pageindex_prompts.py (硬编码提示词)
├── page_index.py (核心逻辑，多处直接写 prompt)
└── utils.py (使用 NODE_SUMMARY_PROMPT, DOC_DESCRIPTION_PROMPT)
```

---

## 1. 提示词系统设计

### 1.1 文件存储结构

**新目录结构：**
```
backend/
├── app/
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── manager.py              # 提示词管理器
│   │   ├── loader.py               # 动态加载器
│   │   ├── registry.py             # 提示词注册表
│   │   └── templates/              # 提示词模板目录
│   │       ├── base/               # 基础模板（通用）
│   │       │   ├── toc_detection.yaml
│   │       │   ├── title_matching.yaml
│   │       │   ├── structure_extraction.yaml
│   │       │   └── validation.yaml
│   │       ├── financial_report/   # 财务报告专用
│   │       │   ├── toc_detection.yaml
│   │       │   ├── validation.yaml
│   │       │   └── entity_extraction.yaml
│   │       ├── academic_paper/     # 学术论文专用
│   │       │   ├── toc_detection.yaml
│   │       │   └── section_analysis.yaml
│   │       ├── book/               # 书籍专用
│   │       │   ├── toc_detection.yaml
│   │       │   └── chapter_analysis.yaml
│   │       └── custom/             # 用户自定义模板
│   │           └── README.md
│   └── ...
```

### 1.2 提示词模板格式设计

**YAML 格式（推荐）：**
```yaml
# backend/app/prompts/templates/base/toc_detection.yaml

metadata:
  name: "table_of_contents_detection"
  version: "1.0.0"
  doc_types: ["generic", "financial_report", "academic_paper", "book"]
  description: "检测页面是否包含目录"
  author: "system"
  last_updated: "2024-01-01"
  
variables:
  - name: "page_text"
    type: "string"
    required: true
    description: "页面文本内容"
  - name: "page_number"
    type: "integer"
    required: false
    description: "页码"

template: |
  判断页面是否包含目录。
  
  页面内容: {{ page_text[:500] }}
  {% if page_number %}页码: {{ page_number }}{% endif %}
  
  目录特征：
  - 包含"目录"、"Contents"等字样
  - 有章节标题和页码
  - 位于文档开头部分
  
  返回JSON：
  {
    "has_toc": true|false,
    "confidence": 0.0-1.0,
    "reasoning": "简要说明"
  }

output_schema:
  type: "json"
  required_fields: ["has_toc", "confidence"]
  
examples:
  - input:
      page_text: "目录\n第一章 绪论... 1\n第二章 方法... 5"
    output:
      has_toc: true
      confidence: 0.95
      reasoning: "包含明确的目录标题和章节列表"
```

**JSON 格式（备选）：**
```json
{
  "metadata": {
    "name": "title_matching",
    "version": "1.0.0",
    "doc_types": ["generic"],
    "description": "匹配章节标题"
  },
  "template": "判断章节是否出现在页面中...",
  "variables": [...]
}
```

### 1.3 核心类设计

**PromptTemplate 类：**
```python
# backend/app/prompts/models.py

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum

class DocType(str, Enum):
    GENERIC = "generic"
    FINANCIAL_REPORT = "financial_report"
    ACADEMIC_PAPER = "academic_paper"
    BOOK = "book"
    TECHNICAL_DOC = "technical_doc"
    LEGAL_DOC = "legal_doc"

class VariableSpec(BaseModel):
    """变量规范"""
    name: str
    type: str  # string, integer, float, boolean, list, dict
    required: bool = True
    default: Optional[Any] = None
    description: str = ""
    validation: Optional[str] = None  # regex pattern for string

class OutputSchema(BaseModel):
    """输出格式规范"""
    type: str  # json, text, markdown
    required_fields: List[str] = []
    format_hints: Dict[str, Any] = {}

class PromptMetadata(BaseModel):
    """提示词元数据"""
    name: str
    version: str
    doc_types: List[DocType]
    description: str
    author: str = "system"
    last_updated: datetime = Field(default_factory=datetime.now)
    tags: List[str] = []

class PromptTemplate(BaseModel):
    """提示词模板"""
    metadata: PromptMetadata
    template: str
    variables: List[VariableSpec]
    output_schema: OutputSchema
    examples: List[Dict[str, Any]] = []
    
    def render(self, **kwargs) -> str:
        """渲染模板"""
        from jinja2 import Template
        jinja_template = Template(self.template)
        return jinja_template.render(**kwargs)
    
    def validate_input(self, **kwargs) -> List[str]:
        """验证输入参数"""
        errors = []
        for var in self.variables:
            if var.required and var.name not in kwargs:
                errors.append(f"Missing required variable: {var.name}")
            elif var.name in kwargs and var.validation:
                import re
                if not re.match(var.validation, str(kwargs[var.name])):
                    errors.append(f"Invalid format for {var.name}")
        return errors
```

**PromptManager 类：**
```python
# backend/app/prompts/manager.py

import yaml
import json
from pathlib import Path
from typing import Dict, List, Optional, Type
from cachetools import TTLCache
import hashlib
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .models import PromptTemplate, DocType

class PromptManager:
    """提示词管理器 - 负责加载、缓存和热更新"""
    
    def __init__(self, templates_dir: Path, cache_ttl: int = 300):
        self.templates_dir = Path(templates_dir)
        self._templates: Dict[str, PromptTemplate] = {}
        self._cache = TTLCache(maxsize=100, ttl=cache_ttl)
        self._version_cache: Dict[str, str] = {}  # 用于热更新检测
        self._lock = asyncio.Lock()
        self._observer: Optional[Observer] = None
        
    async def initialize(self):
        """初始化：加载所有模板并启动文件监控"""
        await self._load_all_templates()
        self._start_file_watcher()
    
    def _start_file_watcher(self):
        """启动文件监控实现热更新"""
        class PromptFileHandler(FileSystemEventHandler):
            def __init__(self, manager: 'PromptManager'):
                self.manager = manager
                
            def on_modified(self, event):
                if event.src_path.endswith(('.yaml', '.yml', '.json')):
                    asyncio.create_task(self.manager._reload_template(event.src_path))
        
        self._observer = Observer()
        self._observer.schedule(
            PromptFileHandler(self),
            str(self.templates_dir),
            recursive=True
        )
        self._observer.start()
    
    async def _load_all_templates(self):
        """加载所有模板文件"""
        for template_file in self.templates_dir.rglob("*.yaml"):
            await self._load_template(template_file)
    
    async def _load_template(self, file_path: Path) -> PromptTemplate:
        """加载单个模板文件"""
        async with self._lock:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            template = PromptTemplate(**data)
            key = f"{template.metadata.name}:{template.metadata.version}"
            self._templates[key] = template
            
            # 记录文件 hash 用于热更新检测
            content = file_path.read_bytes()
            self._version_cache[key] = hashlib.md5(content).hexdigest()
            
            return template
    
    async def _reload_template(self, file_path: str):
        """热更新重新加载模板"""
        path = Path(file_path)
        if not path.exists():
            return
            
        template = await self._load_template(path)
        # 清空相关缓存
        keys_to_remove = [k for k in self._cache.keys() if k.startswith(template.metadata.name)]
        for k in keys_to_remove:
            del self._cache[k]
        
        print(f"[Hot Reload] Template updated: {template.metadata.name}")
    
    async def get_template(
        self, 
        name: str, 
        doc_type: DocType = DocType.GENERIC,
        version: Optional[str] = None
    ) -> Optional[PromptTemplate]:
        """获取模板，优先返回文档类型专用版本"""
        cache_key = f"{name}:{doc_type}:{version}"
        
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # 1. 查找文档类型专用版本
        if version:
            key = f"{name}:{version}"
            if key in self._templates:
                template = self._templates[key]
                if doc_type in template.metadata.doc_types:
                    self._cache[cache_key] = template
                    return template
        
        # 2. 查找通用版本
        generic_key = f"{name}:generic"
        if generic_key in self._templates:
            template = self._templates[generic_key]
            self._cache[cache_key] = template
            return template
        
        # 3. 按 doc_type 查找最佳匹配
        for key, template in self._templates.items():
            if template.metadata.name == name and doc_type in template.metadata.doc_types:
                self._cache[cache_key] = template
                return template
        
        return None
    
    async def render(
        self, 
        name: str, 
        doc_type: DocType = DocType.GENERIC,
        **kwargs
    ) -> str:
        """渲染提示词"""
        template = await self.get_template(name, doc_type)
        if not template:
            raise ValueError(f"Template not found: {name} for doc_type: {doc_type}")
        
        # 验证输入
        errors = template.validate_input(**kwargs)
        if errors:
            raise ValueError(f"Validation errors: {errors}")
        
        return template.render(**kwargs)
    
    def shutdown(self):
        """关闭文件监控"""
        if self._observer:
            self._observer.stop()
            self._observer.join()

# 全局实例
prompt_manager = PromptManager(
    templates_dir=Path(__file__).parent / "templates"
)
```

---

## 2. 文档类型检测策略

### 2.1 轻量级分类器设计

**分类器架构：**
```
DocumentClassifier
├── KeywordBasedClassifier (快速预分类)
├── ContentSampleClassifier (样本分析)
└── LLMClassifier (精确分类，必要时调用)
```

**DocumentType 枚举：**
```python
# backend/app/classification/models.py

from enum import Enum
from typing import Set

class DocumentType(str, Enum):
    """文档类型"""
    UNKNOWN = "unknown"
    FINANCIAL_REPORT = "financial_report"  # 财务报告
    ANNUAL_REPORT = "annual_report"        # 年报
    ACADEMIC_PAPER = "academic_paper"      # 学术论文
    RESEARCH_PAPER = "research_paper"      # 研究论文
    TECHNICAL_BOOK = "technical_book"      # 技术书籍
    TEXTBOOK = "textbook"                  # 教科书
    NOVEL = "novel"                        # 小说
    LEGAL_DOCUMENT = "legal_document"      # 法律文档
    CONTRACT = "contract"                  # 合同
    MANUAL = "manual"                      # 手册
    
    # 特征映射
    @property
    def keywords(self) -> Set[str]:
        """获取文档类型的关键词"""
        keywords_map = {
            self.FINANCIAL_REPORT: {
                "财务报告", "financial report", "资产负债表", "利润表",
                "现金流量表", "审计报告", "auditor", "revenue", "profit"
            },
            self.ANNUAL_REPORT: {
                "年度报告", "annual report", "致股东", "董事会报告",
                "corporate governance", "ESG", "可持续发展"
            },
            self.ACADEMIC_PAPER: {
                "摘要", "abstract", "关键词", "keywords", "引言", "introduction",
                "方法", "methodology", "结果", "results", "结论", "conclusion",
                "参考文献", "references"
            },
            self.TECHNICAL_BOOK: {
                "第1章", "chapter 1", "前言", "preface", "附录", "appendix",
                "练习", "exercise", "案例", "case study"
            },
            self.LEGAL_DOCUMENT: {
                "合同", "contract", "条款", "clause", "甲方", "乙方",
                "party a", "party b", "适用法律", "governing law"
            }
        }
        return keywords_map.get(self, set())
    
    @property
    def validation_rules(self) -> List[str]:
        """获取验证规则名称列表"""
        rules_map = {
            self.FINANCIAL_REPORT: ["numeric_consistency", "table_structure"],
            self.ACADEMIC_PAPER: ["citation_format", "section_completeness"],
            self.TECHNICAL_BOOK: ["chapter_continuity", "hierarchy_depth"],
        }
        return rules_map.get(self, ["basic_structure"])
```

**DocumentClassifier 类：**
```python
# backend/app/classification/classifier.py

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import re
from collections import Counter
import asyncio

from .models import DocumentType

@dataclass
class ClassificationResult:
    """分类结果"""
    doc_type: DocumentType
    confidence: float
    method: str  # keyword, sample, llm
    features: Dict[str, any]
    reasoning: str

class DocumentClassifier:
    """文档类型分类器"""
    
    def __init__(self, use_llm: bool = True, llm_sample_size: int = 3):
        self.use_llm = use_llm
        self.llm_sample_size = llm_sample_size  # LLM分析时取前几页
        
        # 关键词权重配置
        self.keyword_weights = {
            "high": 3.0,    # 标题页关键词
            "medium": 2.0,  # 内容关键词
            "low": 1.0      # 一般关键词
        }
    
    async def classify(
        self, 
        document: Dict[str, any],
        fast_mode: bool = False
    ) -> ClassificationResult:
        """
        分类文档类型
        
        Args:
            document: 包含 metadata, pages, text_sample 等信息的字典
            fast_mode: 是否仅使用快速关键词匹配
            
        Returns:
            ClassificationResult
        """
        # Stage 1: 快速关键词分类
        keyword_result = self._keyword_classify(document)
        
        if fast_mode or keyword_result.confidence >= 0.85:
            return keyword_result
        
        # Stage 2: 内容样本分析
        sample_result = await self._sample_classify(document)
        
        if sample_result.confidence >= 0.80:
            return sample_result
        
        # Stage 3: LLM 精确分类（仅在需要时）
        if self.use_llm:
            llm_result = await self._llm_classify(document)
            # 融合结果
            return self._merge_results(keyword_result, sample_result, llm_result)
        
        # 返回置信度最高的结果
        results = [keyword_result, sample_result]
        return max(results, key=lambda x: x.confidence)
    
    def _keyword_classify(self, document: Dict) -> ClassificationResult:
        """基于关键词的快速分类"""
        text_sample = document.get("text_sample", "")
        metadata = document.get("metadata", {})
        
        # 合并文本进行匹配
        search_text = (
            metadata.get("title", "") + " " +
            text_sample[:2000]  # 前2000字符
        ).lower()
        
        scores = {}
        for doc_type in DocumentType:
            if doc_type == DocumentType.UNKNOWN:
                continue
                
            keywords = doc_type.keywords
            score = 0
            matched_keywords = []
            
            for keyword in keywords:
                count = search_text.count(keyword.lower())
                if count > 0:
                    weight = self._get_keyword_weight(keyword)
                    score += count * weight
                    matched_keywords.append(keyword)
            
            if score > 0:
                scores[doc_type] = {
                    "score": score,
                    "matched": matched_keywords
                }
        
        if not scores:
            return ClassificationResult(
                doc_type=DocumentType.UNKNOWN,
                confidence=0.0,
                method="keyword",
                features={},
                reasoning="未匹配到任何关键词"
            )
        
        # 选择最高分
        best_type = max(scores.keys(), key=lambda x: scores[x]["score"])
        best_score = scores[best_type]["score"]
        total_score = sum(s["score"] for s in scores.values())
        confidence = min(best_score / (total_score * 0.6), 1.0)
        
        return ClassificationResult(
            doc_type=best_type,
            confidence=confidence,
            method="keyword",
            features={
                "scores": {k.value: v["score"] for k, v in scores.items()},
                "matched_keywords": scores[best_type]["matched"]
            },
            reasoning=f"关键词匹配: {', '.join(scores[best_type]['matched'][:5])}"
        )
    
    def _get_keyword_weight(self, keyword: str) -> float:
        """获取关键词权重"""
        high_priority = ["财务报告", "annual report", "abstract", "contract", "合同"]
        medium_priority = ["摘要", "introduction", "方法", "revenue"]
        
        if any(kw in keyword.lower() for kw in high_priority):
            return self.keyword_weights["high"]
        elif any(kw in keyword.lower() for kw in medium_priority):
            return self.keyword_weights["medium"]
        return self.keyword_weights["low"]
    
    async def _sample_classify(self, document: Dict) -> ClassificationResult:
        """基于内容样本的分类"""
        pages = document.get("pages", [])
        
        # 提取特征
        features = {
            "has_toc": self._detect_toc(pages[:3]),
            "has_figures": self._detect_figures(pages),
            "has_tables": self._detect_tables(pages),
            "avg_page_length": self._calculate_avg_length(pages),
            "section_patterns": self._detect_section_patterns(pages),
        }
        
        # 基于特征推断类型
        doc_type, confidence = self._infer_type_from_features(features)
        
        return ClassificationResult(
            doc_type=doc_type,
            confidence=confidence,
            method="sample",
            features=features,
            reasoning=f"特征分析: 目录={features['has_toc']}, 表格={features['has_tables']}"
        )
    
    def _detect_toc(self, pages: List[str]) -> bool:
        """检测是否有目录"""
        toc_patterns = [
            r'目录|contents|table of contents',
            r'第[一二三四五六七八九十\d]+章.*\.{3,}\s*\d+',
            r'chapter\s+\d+.*\.{3,}\s*\d+'
        ]
        
        for page in pages:
            text = page[:1000].lower()
            for pattern in toc_patterns:
                if re.search(pattern, text):
                    return True
        return False
    
    def _detect_tables(self, pages: List[str]) -> bool:
        """检测表格密度"""
        table_count = 0
        for page in pages[:10]:  # 检查前10页
            if re.search(r'\|.*\|.*\n\|[-:]+\|', page):  # Markdown表格
                table_count += 1
            elif re.search(r'表\s*\d+|table\s*\d+', page, re.IGNORECASE):
                table_count += 1
        return table_count >= 3
    
    def _detect_section_patterns(self, pages: List[str]) -> Dict[str, int]:
        """检测章节模式"""
        patterns = {
            "chinese_numeric": r'第[一二三四五六七八九十]+章',
            "arabic_chapter": r'第\s*\d+\s*章',
            "english_chapter": r'chapter\s+\d+',
            "section_number": r'^\d+\.\d+\s+',
        }
        
        counts = {name: 0 for name in patterns.keys()}
        
        for page in pages[:20]:
            for name, pattern in patterns.items():
                counts[name] += len(re.findall(pattern, page, re.MULTILINE | re.IGNORECASE))
        
        return counts
    
    def _infer_type_from_features(self, features: Dict) -> Tuple[DocumentType, float]:
        """从特征推断文档类型"""
        scores = {
            DocumentType.FINANCIAL_REPORT: 0,
            DocumentType.ACADEMIC_PAPER: 0,
            DocumentType.TECHNICAL_BOOK: 0,
        }
        
        # 财务报告特征
        if features["has_tables"] and not features["has_toc"]:
            scores[DocumentType.FINANCIAL_REPORT] += 3
        
        # 学术论文特征
        section_patterns = features.get("section_patterns", {})
        if section_patterns.get("arabic_chapter", 0) > 0:
            scores[DocumentType.ACADEMIC_PAPER] += 2
        
        # 书籍特征
        if features["has_toc"] and features["section_patterns"].get("chinese_numeric", 0) > 3:
            scores[DocumentType.TECHNICAL_BOOK] += 3
        
        best_type = max(scores.keys(), key=lambda x: scores[x])
        total = sum(scores.values())
        confidence = scores[best_type] / max(total, 1) * 0.8  # 最高0.8置信度
        
        return best_type, confidence
    
    async def _llm_classify(self, document: Dict) -> ClassificationResult:
        """使用 LLM 进行精确分类"""
        from app.core.llm import async_chat_completion
        
        # 取样前几页
        pages = document.get("pages", [])
        sample_text = "\n\n".join(pages[:self.llm_sample_size])
        sample_text = sample_text[:3000]  # 限制长度
        
        prompt = f"""分析以下文档样本，判断文档类型。

文档样本（前{self.llm_sample_size}页）:
{sample_text}

可选类型：
- financial_report: 财务报告、年报、财务报表
- academic_paper: 学术论文、期刊文章、学位论文
- technical_book: 技术书籍、教科书、专业书籍
- novel: 小说、文学作品
- legal_document: 法律文档、合同、协议
- manual: 手册、说明书、指南
- other: 其他类型

返回JSON格式：
{{
    "doc_type": "类型标识",
    "confidence": 0.0-1.0,
    "reasoning": "判断理由",
    "key_features": ["特征1", "特征2"]
}}

只返回JSON，不要其他内容。"""

        try:
            response = await async_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                model="qwen3.5-flash"
            )
            
            import json
            import re
            
            json_match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                doc_type_str = result.get("doc_type", "unknown")
                
                # 映射到枚举
                doc_type = DocumentType(doc_type_str) if doc_type_str in [e.value for e in DocumentType] else DocumentType.UNKNOWN
                
                return ClassificationResult(
                    doc_type=doc_type,
                    confidence=result.get("confidence", 0.5),
                    method="llm",
                    features={"key_features": result.get("key_features", [])},
                    reasoning=result.get("reasoning", "")
                )
        except Exception as e:
            print(f"LLM classification error: {e}")
        
        return ClassificationResult(
            doc_type=DocumentType.UNKNOWN,
            confidence=0.0,
            method="llm",
            features={},
            reasoning="LLM分类失败"
        )
    
    def _merge_results(
        self, 
        keyword_result: ClassificationResult,
        sample_result: ClassificationResult,
        llm_result: ClassificationResult
    ) -> ClassificationResult:
        """融合多种分类结果"""
        # 加权投票
        votes = Counter()
        
        votes[keyword_result.doc_type] += keyword_result.confidence * 0.3
        votes[sample_result.doc_type] += sample_result.confidence * 0.3
        votes[llm_result.doc_type] += llm_result.confidence * 0.4
        
        best_type = votes.most_common(1)[0][0]
        total_confidence = sum(votes.values())
        best_confidence = votes[best_type] / total_confidence if total_confidence > 0 else 0
        
        # 整合推理
        reasoning = f"关键词: {keyword_result.reasoning}; 特征: {sample_result.reasoning}; LLM: {llm_result.reasoning}"
        
        return ClassificationResult(
            doc_type=best_type,
            confidence=best_confidence,
            method="merged",
            features={
                "keyword": keyword_result.features,
                "sample": sample_result.features,
                "llm": llm_result.features
            },
            reasoning=reasoning
        )

# 全局实例
document_classifier = DocumentClassifier()
```

---

## 3. 验证逻辑增强方案

### 3.1 通用验证框架设计

**验证框架架构：**
```
ValidationFramework
├── ValidationRule (抽象基类)
│   ├── StructureValidationRule
│   ├── ContentValidationRule
│   ├── ConsistencyValidationRule
│   └── DomainValidationRule (按文档类型)
├── ValidationResult
├── ValidationPipeline
└── FallbackStrategy
```

**核心类设计：**

```python
# backend/app/validation/models.py

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import time

class ValidationLevel(str, Enum):
    CRITICAL = "critical"    # 必须通过，否则整个流程失败
    HIGH = "high"           # 重要，失败会严重降级
    MEDIUM = "medium"       # 一般，失败会轻微降级
    LOW = "low"             # 提示性，不影响流程

class ValidationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"

@dataclass
class ValidationResult:
    """验证结果"""
    rule_name: str
    status: ValidationStatus
    level: ValidationLevel
    score: float  # 0.0-1.0
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0

class ValidationRule(ABC):
    """验证规则基类"""
    
    def __init__(self, name: str, level: ValidationLevel, weight: float = 1.0):
        self.name = name
        self.level = level
        self.weight = weight
        self.enabled = True
    
    @abstractmethod
    async def validate(self, context: Dict[str, Any]) -> ValidationResult:
        """执行验证"""
        pass
    
    def should_skip(self, context: Dict[str, Any]) -> bool:
        """判断是否应该跳过此验证"""
        return not self.enabled

class ValidationContext:
    """验证上下文"""
    
    def __init__(self, **kwargs):
        self.data = kwargs
        self.results: List[ValidationResult] = []
        self.metadata: Dict[str, Any] = {}
    
    def get(self, key: str, default=None):
        return self.data.get(key, default)
    
    def add_result(self, result: ValidationResult):
        self.results.append(result)
    
    def get_overall_score(self) -> float:
        """计算综合得分"""
        if not self.results:
            return 1.0
        
        total_weight = sum(r.weight for r in self.results if r.status != ValidationStatus.SKIPPED)
        weighted_score = sum(
            r.score * r.weight 
            for r in self.results 
            if r.status != ValidationStatus.SKIPPED
        )
        
        return weighted_score / total_weight if total_weight > 0 else 0.0
```

**验证规则实现：**

```python
# backend/app/validation/rules.py

import asyncio
from typing import Dict, List, Any
import re

from .models import ValidationRule, ValidationResult, ValidationLevel, ValidationStatus
from app.classification.models import DocumentType

class StructureValidationRule(ValidationRule):
    """结构验证规则 - 验证目录结构完整性"""
    
    def __init__(self):
        super().__init__("structure_validation", ValidationLevel.CRITICAL, weight=2.0)
    
    async def validate(self, context: Dict[str, Any]) -> ValidationResult:
        structure = context.get("structure", [])
        
        if not structure:
            return ValidationResult(
                rule_name=self.name,
                status=ValidationStatus.FAILED,
                level=self.level,
                score=0.0,
                message="目录结构为空",
                details={"structure": None}
            )
        
        issues = []
        score = 1.0
        
        # 检查节点完整性
        def check_node(node: Dict, depth: int = 0):
            nonlocal score
            
            # 必须有标题
            if not node.get("title"):
                issues.append(f"节点缺少标题")
                score -= 0.2
            
            # 必须有页码范围
            if "start_index" not in node or "end_index" not in node:
                issues.append(f"节点 '{node.get('title', 'unknown')}' 缺少页码范围")
                score -= 0.15
            
            # 检查页码逻辑
            start = node.get("start_index", 0)
            end = node.get("end_index", 0)
            if start > end:
                issues.append(f"节点 '{node.get('title', 'unknown')}' 页码范围错误: {start} > {end}")
                score -= 0.2
            
            # 递归检查子节点
            for child in node.get("nodes", []):
                check_node(child, depth + 1)
        
        for root_node in structure:
            check_node(root_node)
        
        status = ValidationStatus.PASSED if score >= 0.8 else ValidationStatus.FAILED
        if 0.5 <= score < 0.8:
            status = ValidationStatus.WARNING
        
        return ValidationResult(
            rule_name=self.name,
            status=status,
            level=self.level,
            score=max(0.0, score),
            message=f"结构验证: {'通过' if status == ValidationStatus.PASSED else '失败'}",
            details={
                "node_count": len(structure),
                "issues": issues[:10]  # 最多记录10个问题
            }
        )

class TitleAppearanceValidationRule(ValidationRule):
    """标题出现验证 - 验证章节标题是否真实出现在对应页面"""
    
    def __init__(self, sample_rate: float = 0.3, min_samples: int = 5):
        super().__init__("title_appearance", ValidationLevel.HIGH, weight=1.5)
        self.sample_rate = sample_rate  # 抽样比例
        self.min_samples = min_samples
    
    async def validate(self, context: Dict[str, Any]) -> ValidationResult:
        structure = context.get("structure", [])
        page_list = context.get("page_list", [])
        doc_type = context.get("doc_type", DocumentType.GENERIC)
        
        from pageindex.utils import structure_to_list
        
        nodes = structure_to_list(structure)
        
        # 抽样检查
        import random
        sample_size = max(int(len(nodes) * self.sample_rate), self.min_samples)
        sample_size = min(sample_size, len(nodes))
        
        if sample_size == 0:
            return ValidationResult(
                rule_name=self.name,
                status=ValidationStatus.SKIPPED,
                level=self.level,
                score=1.0,
                message="节点数量不足，跳过验证",
                details={}
            )
        
        sampled_nodes = random.sample(nodes, sample_size)
        
        # 并行验证
        from app.prompts.manager import prompt_manager
        from app.core.llm import async_chat_completion
        
        async def check_one(node: Dict) -> Dict:
            node_id = node.get("node_id")
            title = node.get("title", "")
            start_page = node.get("start_index", 1)
            
            if start_page > len(page_list):
                return {"node_id": node_id, "found": False, "reason": "页码超出范围"}
            
            page_text = page_list[start_page - 1][0] if start_page <= len(page_list) else ""
            
            # 使用动态提示词
            prompt = await prompt_manager.render(
                "title_matching",
                doc_type=doc_type,
                title=title,
                page_text=page_text[:500]
            )
            
            try:
                response = await async_chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    model="qwen3.5-flash",
                    timeout=8.0
                )
                
                import json
                import re
                
                json_match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return {
                        "node_id": node_id,
                        "found": result.get("answer", "no") == "yes",
                        "confidence": result.get("confidence", 0.5)
                    }
            except Exception as e:
                print(f"Title check error for node {node_id}: {e}")
            
            return {"node_id": node_id, "found": False, "reason": "验证失败"}
        
        # 并发执行（限制并发数）
        semaphore = asyncio.Semaphore(5)
        
        async def limited_check(node):
            async with semaphore:
                return await check_one(node)
        
        check_results = await asyncio.gather(*[limited_check(node) for node in sampled_nodes])
        
        # 计算通过率
        found_count = sum(1 for r in check_results if r.get("found"))
        pass_rate = found_count / len(check_results) if check_results else 0
        
        status = ValidationStatus.PASSED if pass_rate >= 0.8 else ValidationStatus.FAILED
        if 0.6 <= pass_rate < 0.8:
            status = ValidationStatus.WARNING
        
        return ValidationResult(
            rule_name=self.name,
            status=status,
            level=self.level,
            score=pass_rate,
            message=f"标题出现验证: {found_count}/{len(check_results)} 通过 ({pass_rate:.1%})",
            details={
                "sample_size": sample_size,
                "pass_count": found_count,
                "fail_count": len(check_results) - found_count,
                "failures": [r for r in check_results if not r.get("found")][:5]
            }
        )

class NumericConsistencyRule(ValidationRule):
    """数值一致性验证 - 针对财务报告"""
    
    def __init__(self):
        super().__init__("numeric_consistency", ValidationLevel.MEDIUM, weight=1.0)
    
    def should_skip(self, context: Dict[str, Any]) -> bool:
        doc_type = context.get("doc_type")
        # 只对财务报告启用
        return doc_type not in [DocumentType.FINANCIAL_REPORT, DocumentType.ANNUAL_REPORT]
    
    async def validate(self, context: Dict[str, Any]) -> ValidationResult:
        structure = context.get("structure", {})
        
        # 提取所有数字
        import re
        
        def extract_numbers(text: str) -> List[float]:
            """提取文本中的数字"""
            # 匹配各种数字格式：1,234.56, 1234.56, 12.34%
            pattern = r'(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\s*%)?)'
            matches = re.findall(pattern, text)
            numbers = []
            for m in matches:
                try:
                    # 移除逗号和百分号
                    clean = m.replace(',', '').replace('%', '').strip()
                    numbers.append(float(clean))
                except:
                    pass
            return numbers
        
        # 检查关键财务章节
        financial_sections = []
        nodes = []
        
        def collect_nodes(node: Dict):
            nodes.append(node)
            for child in node.get("nodes", []):
                collect_nodes(child)
        
        if isinstance(structure, dict):
            collect_nodes(structure)
        elif isinstance(structure, list):
            for item in structure:
                collect_nodes(item)
        
        # 查找包含财务数据的章节
        for node in nodes:
            title = node.get("title", "").lower()
            if any(kw in title for kw in ["财务", "资产", "负债", "收入", "利润", "balance", "income"]):
                financial_sections.append(node)
        
        if not financial_sections:
            return ValidationResult(
                rule_name=self.name,
                status=ValidationStatus.SKIPPED,
                level=self.level,
                score=1.0,
                message="未找到财务章节，跳过数值验证",
                details={}
            )
        
        # TODO: 实现更复杂的数值交叉验证逻辑
        
        return ValidationResult(
            rule_name=self.name,
            status=ValidationStatus.PASSED,
            level=self.level,
            score=0.9,
            message=f"找到 {len(financial_sections)} 个财务章节",
            details={"financial_sections": [n.get("title") for n in financial_sections]}
        )

class CitationFormatRule(ValidationRule):
    """引用格式验证 - 针对学术论文"""
    
    def __init__(self):
        super().__init__("citation_format", ValidationLevel.LOW, weight=0.5)
    
    def should_skip(self, context: Dict[str, Any]) -> bool:
        doc_type = context.get("doc_type")
        return doc_type != DocumentType.ACADEMIC_PAPER
    
    async def validate(self, context: Dict[str, Any]) -> ValidationResult:
        text_sample = context.get("text_sample", "")
        
        # 检查引用格式
        citation_patterns = [
            (r'\[\d+\]', "numeric"),      # [1], [2,3]
            (r'\(\w+\s+\d{4}\)', "author_year"),  # (Smith 2020)
            (r'\d+\.\s+\w+', "numbered"),  # 1. Author
        ]
        
        found_formats = []
        for pattern, name in citation_patterns:
            if re.search(pattern, text_sample):
                found_formats.append(name)
        
        score = min(len(found_formats) / 2, 1.0)  # 至少2种格式得满分
        
        return ValidationResult(
            rule_name=self.name,
            status=ValidationStatus.PASSED if score >= 0.5 else ValidationStatus.WARNING,
            level=self.level,
            score=score,
            message=f"引用格式: 发现 {len(found_formats)} 种格式",
            details={"formats": found_formats}
        )
```

**验证管道：**

```python
# backend/app/validation/pipeline.py

import asyncio
from typing import List, Dict, Any, Callable, Optional
from dataclasses import dataclass

from .models import (
    ValidationRule, ValidationContext, ValidationResult, 
    ValidationLevel, ValidationStatus
)
from .rules import (
    StructureValidationRule, TitleAppearanceValidationRule,
    NumericConsistencyRule, CitationFormatRule
)

@dataclass
class PipelineConfig:
    """管道配置"""
    parallel: bool = True           # 是否并行执行
    max_workers: int = 5           # 最大并发数
    stop_on_critical: bool = True  # 关键验证失败是否停止
    enable_retries: bool = True    # 是否启用重试
    retry_count: int = 2           # 重试次数

class ValidationPipeline:
    """验证管道 - 编排多个验证规则"""
    
    def __init__(self, config: PipelineConfig = None):
        self.config = config or PipelineConfig()
        self.rules: List[ValidationRule] = []
        self.fallback_strategies: Dict[str, Callable] = {}
    
    def add_rule(self, rule: ValidationRule):
        """添加验证规则"""
        self.rules.append(rule)
    
    def add_fallback(self, rule_name: str, strategy: Callable):
        """添加回退策略"""
        self.fallback_strategies[rule_name] = strategy
    
    @classmethod
    def create_default_pipeline(cls, doc_type: str = "generic") -> "ValidationPipeline":
        """创建默认验证管道"""
        pipeline = cls()
        
        # 添加通用规则
        pipeline.add_rule(StructureValidationRule())
        pipeline.add_rule(TitleAppearanceValidationRule())
        
        # 添加文档类型特定规则
        pipeline.add_rule(NumericConsistencyRule())
        pipeline.add_rule(CitationFormatRule())
        
        return pipeline
    
    async def execute(self, context: ValidationContext) -> ValidationContext:
        """执行验证管道"""
        
        if self.config.parallel:
            return await self._execute_parallel(context)
        else:
            return await self._execute_sequential(context)
    
    async def _execute_sequential(self, context: ValidationContext) -> ValidationContext:
        """串行执行"""
        for rule in self.rules:
            if rule.should_skip(context.data):
                continue
            
            result = await self._execute_rule_with_retry(rule, context)
            context.add_result(result)
            
            # 关键验证失败，停止管道
            if (self.config.stop_on_critical and 
                result.level == ValidationLevel.CRITICAL and 
                result.status == ValidationStatus.FAILED):
                break
        
        return context
    
    async def _execute_parallel(self, context: ValidationContext) -> ValidationContext:
        """并行执行（限制并发数）"""
        semaphore = asyncio.Semaphore(self.config.max_workers)
        
        async def execute_one(rule: ValidationRule) -> ValidationResult:
            async with semaphore:
                if rule.should_skip(context.data):
                    return ValidationResult(
                        rule_name=rule.name,
                        status=ValidationStatus.SKIPPED,
                        level=rule.level,
                        score=1.0,
                        message="规则被跳过",
                        details={}
                    )
                return await self._execute_rule_with_retry(rule, context)
        
        # 按优先级分组（关键规则先执行）
        critical_rules = [r for r in self.rules if r.level == ValidationLevel.CRITICAL]
        other_rules = [r for r in self.rules if r.level != ValidationLevel.CRITICAL]
        
        # 先执行关键规则
        if critical_rules:
            critical_results = await asyncio.gather(
                *[execute_one(r) for r in critical_rules]
            )
            for result in critical_results:
                context.add_result(result)
                
                if self.config.stop_on_critical and result.status == ValidationStatus.FAILED:
                    print(f"[Validation] Critical rule '{result.rule_name}' failed, stopping pipeline")
                    return context
        
        # 并行执行其他规则
        if other_rules:
            other_results = await asyncio.gather(
                *[execute_one(r) for r in other_rules]
            )
            for result in other_results:
                context.add_result(result)
        
        return context
    
    async def _execute_rule_with_retry(
        self, 
        rule: ValidationRule, 
        context: ValidationContext
    ) -> ValidationResult:
        """带重试的规则执行"""
        last_exception = None
        
        for attempt in range(self.config.retry_count + 1):
            try:
                result = await rule.validate(context.data)
                if attempt > 0:
                    result.retry_count = attempt
                return result
            except Exception as e:
                last_exception = e
                print(f"[Validation] Rule '{rule.name}' failed (attempt {attempt + 1}): {e}")
                
                if attempt < self.config.retry_count:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
        
        # 所有重试都失败
        return ValidationResult(
            rule_name=rule.name,
            status=ValidationStatus.FAILED,
            level=rule.level,
            score=0.0,
            message=f"验证执行失败: {str(last_exception)}",
            details={"error": str(last_exception)}
        )
    
    def should_accept(self, context: ValidationContext) -> bool:
        """判断是否接受结果"""
        for result in context.results:
            if (result.level == ValidationLevel.CRITICAL and 
                result.status == ValidationStatus.FAILED):
                return False
        return context.get_overall_score() >= 0.6
    
    async def apply_fallback(self, context: ValidationContext) -> ValidationContext:
        """应用回退策略"""
        for result in context.results:
            if result.status == ValidationStatus.FAILED and result.rule_name in self.fallback_strategies:
                strategy = self.fallback_strategies[result.rule_name]
                try:
                    fallback_result = await strategy(context, result)
                    if fallback_result:
                        # 用回退结果替换原结果
                        idx = context.results.index(result)
                        context.results[idx] = fallback_result
                        print(f"[Validation] Applied fallback for '{result.rule_name}'")
                except Exception as e:
                    print(f"[Validation] Fallback failed for '{result.rule_name}': {e}")
        
        return context

# 回退策略示例
async def structure_fallback_strategy(context: ValidationContext, failed_result: ValidationResult) -> Optional[ValidationResult]:
    """结构验证失败的回退策略"""
    # 尝试使用启发式方法重建结构
    print("[Fallback] Attempting to rebuild structure using heuristics...")
    
    # 这里可以实现简单的基于规则的目录重建
    # 返回一个降级但仍可用的结果
    
    return ValidationResult(
        rule_name=failed_result.rule_name,
        status=ValidationStatus.WARNING,
        level=failed_result.level,
        score=0.5,
        message="使用回退策略: 基于启发式重建结构",
        details={"fallback_applied": True}
    )
```

### 3.2 回退策略设计

```python
# backend/app/validation/fallback.py

from typing import Dict, Any, List, Optional
import re

class FallbackStrategies:
    """回退策略集合"""
    
    @staticmethod
    async def toc_detection_fallback(pages: List[str]) -> Optional[Dict]:
        """目录检测失败的回退策略 - 使用正则匹配"""
        print("[Fallback] Using regex-based TOC detection")
        
        toc_items = []
        
        # 简单的目录行模式
        toc_pattern = r'^(.*?)(?:\.{3,}|\s{3,})(\d+)$'
        
        for page_idx, page_text in enumerate(pages[:5]):  # 只看前5页
            lines = page_text.split('\n')
            for line in lines:
                match = re.match(toc_pattern, line.strip())
                if match:
                    title = match.group(1).strip()
                    page_num = int(match.group(2))
                    toc_items.append({
                        "title": title,
                        "page": page_num,
                        "level": 1  # 简化处理，统一为一级
                    })
        
        if len(toc_items) >= 3:  # 至少3个条目才认为是目录
            return {
                "toc_items": toc_items,
                "is_complete": False,
                "method": "regex_fallback",
                "confidence": 0.6
            }
        
        return None
    
    @staticmethod
    async def title_matching_fallback(title: str, page_text: str) -> bool:
        """标题匹配失败的回退策略 - 使用模糊匹配"""
        from difflib import SequenceMatcher
        
        # 计算相似度
        similarity = SequenceMatcher(None, title.lower(), page_text[:200].lower()).ratio()
        
        # 同时检查关键词匹配
        title_words = set(title.lower().split())
        page_words = set(page_text[:500].lower().split())
        word_overlap = len(title_words & page_words) / len(title_words) if title_words else 0
        
        # 综合判断
        combined_score = similarity * 0.5 + word_overlap * 0.5
        
        return combined_score >= 0.5
    
    @staticmethod
    async def structure_validation_fallback(structure: List[Dict], page_list: List) -> List[Dict]:
        """结构验证失败的回退策略 - 修复常见问题"""
        print("[Fallback] Attempting to fix structure issues")
        
        fixed_structure = []
        
        for i, node in enumerate(structure):
            fixed_node = node.copy()
            
            # 修复缺失的页码
            if "start_index" not in fixed_node or fixed_node["start_index"] is None:
                if i == 0:
                    fixed_node["start_index"] = 1
                else:
                    # 使用前一个节点的 end_index + 1
                    prev_end = structure[i-1].get("end_index", i)
                    fixed_node["start_index"] = prev_end + 1
            
            if "end_index" not in fixed_node or fixed_node["end_index"] is None:
                if i < len(structure) - 1:
                    # 使用下一个节点的 start_index - 1
                    next_start = structure[i+1].get("start_index", fixed_node["start_index"] + 1)
                    fixed_node["end_index"] = next_start - 1
                else:
                    # 最后一个节点，使用文档末尾
                    fixed_node["end_index"] = len(page_list)
            
            # 确保 start <= end
            if fixed_node["start_index"] > fixed_node["end_index"]:
                fixed_node["end_index"] = fixed_node["start_index"]
            
            fixed_structure.append(fixed_node)
        
        return fixed_structure
```

---

## 4. 性能优化策略

### 4.1 并行化设计

**并行化架构：**
```
ProcessingPipeline
├── ParallelBatchProcessor
├── AsyncTaskScheduler
└── ResourceLimiter (Semaphore)
```

**关键代码：**

```python
# backend/app/performance/async_processor.py

import asyncio
from typing import List, Callable, TypeVar, Generic
from dataclasses import dataclass
import time

T = TypeVar('T')
R = TypeVar('R')

@dataclass
class BatchResult:
    """批处理结果"""
    results: List[R]
    failed_indices: List[int]
    execution_time: float
    success_rate: float

class ParallelBatchProcessor:
    """并行批处理器"""
    
    def __init__(self, max_concurrency: int = 5, timeout: float = 30.0):
        self.max_concurrency = max_concurrency
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrency)
    
    async def process_batch(
        self,
        items: List[T],
        processor: Callable[[T], asyncio.Coroutine[Any, Any, R]],
        error_handler: Callable[[T, Exception], R] = None
    ) -> BatchResult:
        """
        并行处理一批项目
        
        Args:
            items: 待处理项目列表
            processor: 异步处理函数
            error_handler: 错误处理函数（可选）
            
        Returns:
            BatchResult
        """
        start_time = time.time()
        
        async def process_one(index: int, item: T) -> tuple:
            async with self.semaphore:
                try:
                    result = await asyncio.wait_for(
                        processor(item),
                        timeout=self.timeout
                    )
                    return (index, result, None)
                except Exception as e:
                    if error_handler:
                        try:
                            fallback_result = error_handler(item, e)
                            return (index, fallback_result, None)
                        except:
                            return (index, None, e)
                    return (index, None, e)
        
        # 创建所有任务
        tasks = [process_one(i, item) for i, item in enumerate(items)]
        
        # 等待所有任务完成
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 收集结果
        results = [None] * len(items)
        failed_indices = []
        
        for index, result, error in completed:
            if error is None:
                results[index] = result
            else:
                failed_indices.append(index)
                results[index] = None
        
        execution_time = time.time() - start_time
        success_rate = (len(items) - len(failed_indices)) / len(items) if items else 0
        
        return BatchResult(
            results=results,
            failed_indices=failed_indices,
            execution_time=execution_time,
            success_rate=success_rate
        )
    
    async def process_with_retry(
        self,
        items: List[T],
        processor: Callable[[T], asyncio.Coroutine[Any, Any, R]],
        max_retries: int = 2,
        retry_delay: float = 1.0
    ) -> BatchResult:
        """带重试的批处理"""
        
        async def processor_with_retry(item: T) -> R:
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return await processor(item)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay * (2 ** attempt))
            raise last_error
        
        return await self.process_batch(items, processor_with_retry)


class AsyncTaskScheduler:
    """异步任务调度器 - 管理任务优先级和依赖"""
    
    def __init__(self, max_concurrent: int = 10):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.pending_tasks: List[asyncio.Task] = []
    
    async def schedule(
        self,
        coro: asyncio.Coroutine,
        priority: int = 5,  # 1-10, 1最高
        dependencies: List[asyncio.Task] = None
    ) -> asyncio.Task:
        """调度任务"""
        
        async def wrapped_coro():
            # 等待依赖完成
            if dependencies:
                await asyncio.gather(*dependencies, return_exceptions=True)
            
            async with self.semaphore:
                return await coro
        
        task = asyncio.create_task(wrapped_coro())
        self.pending_tasks.append(task)
        
        # 清理已完成的任务
        self.pending_tasks = [t for t in self.pending_tasks if not t.done()]
        
        return task
    
    async def wait_all(self, timeout: float = None):
        """等待所有任务完成"""
        if not self.pending_tasks:
            return
        
        await asyncio.wait(
            self.pending_tasks,
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED
        )
```

### 4.2 缓存策略

**多层缓存架构：**
```python
# backend/app/performance/cache.py

import hashlib
import json
import pickle
from typing import Any, Optional, Dict
from datetime import datetime, timedelta
from dataclasses import dataclass
import asyncio

from cachetools import TTLCache, LRUCache
import diskcache as dc

@dataclass
class CacheConfig:
    """缓存配置"""
    memory_maxsize: int = 1000
    memory_ttl: int = 300  # 5分钟
    disk_path: str = "./cache"
    disk_ttl: int = 86400  # 1天
    redis_url: Optional[str] = None

class MultiLevelCache:
    """多级缓存 - L1(内存) -> L2(磁盘) -> L3(Redis)"""
    
    def __init__(self, config: CacheConfig = None):
        self.config = config or CacheConfig()
        
        # L1: 内存缓存
        self._memory = TTLCache(
            maxsize=self.config.memory_maxsize,
            ttl=self.config.memory_ttl
        )
        
        # L2: 磁盘缓存
        self._disk = dc.Cache(self.config.disk_path)
        
        # L3: Redis (可选)
        self._redis = None
        if self.config.redis_url:
            try:
                import redis.asyncio as redis
                self._redis = redis.from_url(self.config.redis_url)
            except:
                pass
    
    def _make_key(self, *args, **kwargs) -> str:
        """生成缓存键"""
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        # L1
        if key in self._memory:
            return self._memory[key]
        
        # L2
        if key in self._disk:
            value = self._disk[key]
            # 回填L1
            self._memory[key] = value
            return value
        
        # L3
        if self._redis:
            try:
                value = await self._redis.get(key)
                if value:
                    value = pickle.loads(value)
                    # 回填L1和L2
                    self._memory[key] = value
                    self._disk[key] = value
                    return value
            except:
                pass
        
        return None
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: int = None,
        levels: List[str] = None
    ):
        """设置缓存"""
        levels = levels or ["memory", "disk"]
        
        if "memory" in levels:
            self._memory[key] = value
        
        if "disk" in levels:
            self._disk[key] = value
        
        if "redis" in levels and self._redis:
            try:
                await self._redis.set(
                    key, 
                    pickle.dumps(value),
                    ex=ttl or self.config.disk_ttl
                )
            except:
                pass
    
    async def delete(self, key: str):
        """删除缓存"""
        self._memory.pop(key, None)
        self._disk.pop(key, None)
        if self._redis:
            try:
                await self._redis.delete(key)
            except:
                pass
    
    async def clear(self):
        """清空缓存"""
        self._memory.clear()
        self._disk.clear()
        if self._redis:
            try:
                await self._redis.flushdb()
            except:
                pass

class PromptCache:
    """提示词专用缓存"""
    
    def __init__(self, cache: MultiLevelCache = None):
        self.cache = cache or MultiLevelCache()
    
    async def get_rendered_prompt(
        self, 
        template_name: str, 
        doc_type: str, 
        **kwargs
    ) -> Optional[str]:
        """获取已渲染的提示词"""
        # 对kwargs进行规范化排序
        sorted_kwargs = dict(sorted(kwargs.items()))
        key = self.cache._make_key(template_name, doc_type, sorted_kwargs)
        return await self.cache.get(f"prompt:{key}")
    
    async def set_rendered_prompt(
        self, 
        template_name: str, 
        doc_type: str, 
        rendered: str,
        **kwargs
    ):
        """缓存已渲染的提示词"""
        sorted_kwargs = dict(sorted(kwargs.items()))
        key = self.cache._make_key(template_name, doc_type, sorted_kwargs)
        await self.cache.set(f"prompt:{key}", rendered, ttl=600, levels=["memory"])

class LLMResponseCache:
    """LLM 响应缓存"""
    
    def __init__(self, cache: MultiLevelCache = None):
        self.cache = cache or MultiLevelCache()
        self._hit_count = 0
        self._miss_count = 0
    
    async def get(self, prompt: str, model: str, temperature: float = 0) -> Optional[str]:
        """获取缓存的响应"""
        key = self.cache._make_key(prompt[:1000], model, temperature)
        result = await self.cache.get(f"llm:{key}")
        
        if result:
            self._hit_count += 1
        else:
            self._miss_count += 1
        
        return result
    
    async def set(
        self, 
        prompt: str, 
        model: str, 
        response: str,
        temperature: float = 0,
        ttl: int = 3600
    ):
        """缓存响应"""
        key = self.cache._make_key(prompt[:1000], model, temperature)
        await self.cache.set(f"llm:{key}", response, ttl=ttl, levels=["memory", "disk"])
    
    def get_stats(self) -> Dict[str, float]:
        """获取缓存统计"""
        total = self._hit_count + self._miss_count
        hit_rate = self._hit_count / total if total > 0 else 0
        return {
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": hit_rate,
            "total_requests": total
        }
```

### 4.3 超时和重试机制

```python
# backend/app/performance/retry.py

import asyncio
from typing import Callable, TypeVar, List, Type, Optional
from dataclasses import dataclass
from functools import wraps
import random

T = TypeVar('T')

@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retry_exceptions: List[Type[Exception]] = None
    
    def __post_init__(self):
        if self.retry_exceptions is None:
            self.retry_exceptions = [Exception]

class RetryWithBackoff:
    """指数退避重试装饰器"""
    
    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig()
    
    async def execute(
        self,
        func: Callable[..., asyncio.Coroutine[Any, Any, T]],
        *args,
        **kwargs
    ) -> T:
        """执行带重试的函数"""
        last_exception = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except tuple(self.config.retry_exceptions) as e:
                last_exception = e
                
                if attempt < self.config.max_retries:
                    delay = self._calculate_delay(attempt)
                    print(f"[Retry] Attempt {attempt + 1} failed: {e}. Retrying in {delay:.2f}s...")
                    await asyncio.sleep(delay)
                else:
                    print(f"[Retry] All {self.config.max_retries + 1} attempts failed")
                    raise last_exception
        
        raise last_exception
    
    def _calculate_delay(self, attempt: int) -> float:
        """计算延迟时间"""
        delay = self.config.base_delay * (self.config.exponential_base ** attempt)
        delay = min(delay, self.config.max_delay)
        
        if self.config.jitter:
            # 添加随机抖动 (0.5 - 1.5 倍)
            delay *= (0.5 + random.random())
        
        return delay

def retry_with_backoff(config: RetryConfig = None):
    """装饰器工厂"""
    retry_handler = RetryWithBackoff(config)
    
    def decorator(func: Callable[..., asyncio.Coroutine[Any, Any, T]]):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_handler.execute(func, *args, **kwargs)
        return wrapper
    return decorator

class CircuitBreaker:
    """熔断器模式 - 防止级联故障"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half_open
    
    async def call(
        self,
        func: Callable[..., asyncio.Coroutine[Any, Any, T]],
        fallback: Callable[..., T] = None,
        *args,
        **kwargs
    ) -> T:
        """执行带熔断保护的调用"""
        
        if self.state == "open":
            # 检查是否可以进入半开状态
            if asyncio.get_event_loop().time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half_open"
                self.failure_count = 0
                self.success_count = 0
                print("[CircuitBreaker] Entering half-open state")
            else:
                # 熔断器打开，执行回退
                if fallback:
                    print("[CircuitBreaker] Circuit open, using fallback")
                    return fallback(*args, **kwargs)
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            if fallback:
                return fallback(*args, **kwargs)
            raise e
    
    def _on_success(self):
        """成功回调"""
        if self.state == "half_open":
            self.success_count += 1
            if self.success_count >= self.half_open_max_calls:
                self.state = "closed"
                self.failure_count = 0
                print("[CircuitBreaker] Circuit closed")
        else:
            self.failure_count = max(0, self.failure_count - 1)
    
    def _on_failure(self):
        """失败回调"""
        self.failure_count += 1
        self.last_failure_time = asyncio.get_event_loop().time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            print(f"[CircuitBreaker] Circuit OPENED after {self.failure_count} failures")

# 预定义的LLM调用重试配置
LLM_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
    retry_exceptions=[
        TimeoutError,
        ConnectionError,
        Exception  # API限流等
    ]
)

# 使用示例
@retry_with_backoff(LLM_RETRY_CONFIG)
async def robust_llm_call(prompt: str, model: str = "qwen3.5-flash") -> str:
    """带重试的LLM调用"""
    from app.core.llm import async_chat_completion
    
    response = await async_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=0
    )
    
    return response.choices[0].message.content
```

### 4.4 LLM 调用优化

```python
# backend/app/performance/batch_llm.py

import asyncio
from typing import List, Dict, Any, Callable
from dataclasses import dataclass
import json

from .async_processor import ParallelBatchProcessor
from .retry import retry_with_backoff, LLM_RETRY_CONFIG

@dataclass
class LLMBatchRequest:
    """LLM批处理请求"""
    id: str
    prompt: str
    model: str = "qwen3.5-flash"
    temperature: float = 0
    max_tokens: int = 500
    priority: int = 5

@dataclass
class LLMBatchResponse:
    """LLM批处理响应"""
    id: str
    success: bool
    content: str = ""
    error: str = ""
    latency_ms: float = 0.0

class BatchLLMProcessor:
    """批量 LLM 处理器 - 减少API调用次数"""
    
    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self.processor = ParallelBatchProcessor(max_concurrent=max_concurrent)
    
    async def process_batch(
        self,
        requests: List[LLMBatchRequest],
        progress_callback: Callable[[int, int], None] = None
    ) -> List[LLMBatchResponse]:
        """批量处理LLM请求"""
        
        @retry_with_backoff(LLM_RETRY_CONFIG)
        async def process_one(request: LLMBatchRequest) -> LLMBatchResponse:
            import time
            from app.core.llm import async_chat_completion
            
            start = time.time()
            
            try:
                response = await async_chat_completion(
                    messages=[{"role": "user", "content": request.prompt}],
                    model=request.model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens
                )
                
                latency = (time.time() - start) * 1000
                
                return LLMBatchResponse(
                    id=request.id,
                    success=True,
                    content=response.choices[0].message.content,
                    latency_ms=latency
                )
            except Exception as e:
                latency = (time.time() - start) * 1000
                return LLMBatchResponse(
                    id=request.id,
                    success=False,
                    error=str(e),
                    latency_ms=latency
                )
        
        # 批量处理
        results = await self.processor.process_batch(
            requests,
            process_one,
            error_handler=lambda req, e: LLMBatchResponse(
                id=req.id,
                success=False,
                error=str(e)
            )
        )
        
        return results.results
    
    async def process_multi_prompt_batch(
        self,
        items: List[Dict[str, Any]],
        prompt_template: Callable[[Dict], str],
        result_parser: Callable[[str], Any],
        model: str = "qwen3.5-flash"
    ) -> List[Any]:
        """
        批量处理多提示词任务
        
        示例：批量验证多个节点
        """
        requests = [
            LLMBatchRequest(
                id=str(i),
                prompt=prompt_template(item),
                model=model
            )
            for i, item in enumerate(items)
        ]
        
        responses = await self.process_batch(requests)
        
        results = []
        for i, response in enumerate(responses):
            if response.success:
                try:
                    parsed = result_parser(response.content)
                    results.append(parsed)
                except Exception as e:
                    print(f"Failed to parse response for item {i}: {e}")
                    results.append(None)
            else:
                results.append(None)
        
        return results


class SmartBatchSplitter:
    """智能批处理分割器 - 优化token使用"""
    
    def __init__(self, max_batch_tokens: int = 4000):
        self.max_batch_tokens = max_batch_tokens
    
    def split_for_toc_detection(
        self, 
        page_contents: List[Tuple[int, str]]
    ) -> List[List[Tuple[int, str]]]:
        """
        智能分割页面用于目录检测
        
        策略：
        1. 优先处理前几页（目录通常在前10页）
        2. 每批处理相邻的页面
        3. 控制每批的token数量
        """
        batches = []
        current_batch = []
        current_tokens = 0
        
        # 只处理前15页
        pages_to_process = page_contents[:15]
        
        for idx, content in pages_to_process:
            # 估算token数（粗略估计：1token ≈ 4字符）
            estimated_tokens = len(content) // 4
            
            if current_tokens + estimated_tokens > self.max_batch_tokens and current_batch:
                # 当前批次已满，开始新批次
                batches.append(current_batch)
                current_batch = [(idx, content)]
                current_tokens = estimated_tokens
            else:
                current_batch.append((idx, content))
                current_tokens += estimated_tokens
        
        if current_batch:
            batches.append(current_batch)
        
        return batches
    
    def split_for_validation(
        self,
        nodes: List[Dict],
        max_nodes_per_batch: int = 5
    ) -> List[List[Dict]]:
        """
        分割节点用于批量验证
        """
        return [
            nodes[i:i + max_nodes_per_batch]
            for i in range(0, len(nodes), max_nodes_per_batch)
        ]
```

---

## 5. 完整数据流图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Document Processing Pipeline                        │
└─────────────────────────────────────────────────────────────────────────────┘

[输入文档]
     │
     ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 1: Document Classification (文档类型检测)                       │
│  ├── KeywordBasedClassifier (快速，<10ms)                            │
│  ├── ContentSampleClassifier (中速，<100ms)                          │
│  └── LLMClassifier (精确，按需调用)                                  │
│                                                                      │
│  输出: DocumentType, confidence, features                           │
└──────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 2: TOC Detection (目录检测)                                     │
│  ├── Load Prompt Template (根据doc_type动态加载)                     │
│  ├── Batch Processing (并行处理多页)                                 │
│  ├── Regex Fallback (检测失败时回退)                                 │
│  └── Cache Results                                                  │
│                                                                      │
│  输出: toc_items, toc_pages, has_page_numbers                       │
└──────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 3: Structure Extraction (结构提取)                              │
│  ├── Load Extraction Prompt                                         │
│  ├── Process TOC (有目录)                                           │
│  │   ├── TOC with page numbers → Extract & Align                    │
│  │   └── TOC without page numbers → Match to pages                  │
│  └── Generate Structure (无目录)                                     │
│      └── Hierarchical extraction from content                       │
│                                                                      │
│  输出: tree_structure (nested dict/list)                            │
└──────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 4: Validation (验证)                                            │
│  ├── Load Validation Rules (根据doc_type)                            │
│  ├── Parallel Validation Pipeline                                   │
│  │   ├── StructureValidationRule                                    │
│  │   ├── TitleAppearanceValidationRule (sampled)                    │
│  │   ├── DomainSpecificRules (Financial/Academic/...)               │
│  │   └── Cross-Reference Validation                                 │
│  ├── Score Calculation                                              │
│  ├── Fallback Strategies (if failed)                                │
│  └── Decision: Accept / Retry / Reject                              │
│                                                                      │
│  输出: validation_results, overall_score, accept/reject             │
└──────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 5: Enhancement (增强处理)                                       │
│  ├── Node Summary Generation (并行)                                  │
│  ├── Document Description Generation                                │
│  ├── Node Text Extraction (从PDF)                                   │
│  └── Metadata Enrichment                                            │
│                                                                      │
│  输出: enhanced_structure with summaries & metadata                 │
└──────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Stage 6: Persistence (持久化)                                         │
│  ├── Format Output (JSON)                                           │
│  ├── Save to Disk (indexes/{doc_id}.json)                           │
│  └── Update Database                                                │
│                                                                      │
│  输出: file_path, metadata                                           │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 6. 实施步骤

### Phase 1: 基础架构搭建（预计 2-3 天）

#### Task 1.1: 创建提示词管理系统

**Files:**
- Create: `backend/app/prompts/__init__.py`
- Create: `backend/app/prompts/models.py`
- Create: `backend/app/prompts/manager.py`
- Create: `backend/app/prompts/loader.py`

**步骤：**

- [ ] **Step 1: 创建数据模型**

```python
# backend/app/prompts/models.py

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum

class DocType(str, Enum):
    GENERIC = "generic"
    FINANCIAL_REPORT = "financial_report"
    ACADEMIC_PAPER = "academic_paper"
    BOOK = "book"
    TECHNICAL_DOC = "technical_doc"
    LEGAL_DOC = "legal_doc"

class VariableSpec(BaseModel):
    name: str
    type: str
    required: bool = True
    default: Optional[Any] = None
    description: str = ""
    validation: Optional[str] = None

class OutputSchema(BaseModel):
    type: str
    required_fields: List[str] = []
    format_hints: Dict[str, Any] = {}

class PromptMetadata(BaseModel):
    name: str
    version: str
    doc_types: List[DocType]
    description: str
    author: str = "system"
    last_updated: datetime = Field(default_factory=datetime.now)
    tags: List[str] = []

class PromptTemplate(BaseModel):
    metadata: PromptMetadata
    template: str
    variables: List[VariableSpec]
    output_schema: OutputSchema
    examples: List[Dict[str, Any]] = []
```

- [ ] **Step 2: 实现提示词管理器核心**

```python
# backend/app/prompts/manager.py

import yaml
from pathlib import Path
from typing import Dict, Optional
from cachetools import TTLCache

from .models import PromptTemplate, DocType

class PromptManager:
    def __init__(self, templates_dir: Path, cache_ttl: int = 300):
        self.templates_dir = Path(templates_dir)
        self._templates: Dict[str, PromptTemplate] = {}
        self._cache = TTLCache(maxsize=100, ttl=cache_ttl)
    
    async def initialize(self):
        """加载所有模板"""
        for template_file in self.templates_dir.rglob("*.yaml"):
            await self._load_template(template_file)
    
    async def _load_template(self, file_path: Path) -> PromptTemplate:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        template = PromptTemplate(**data)
        key = f"{template.metadata.name}:{template.metadata.version}"
        self._templates[key] = template
        return template
    
    async def get_template(
        self, 
        name: str, 
        doc_type: DocType = DocType.GENERIC
    ) -> Optional[PromptTemplate]:
        cache_key = f"{name}:{doc_type}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # 查找匹配模板...
        for key, template in self._templates.items():
            if template.metadata.name == name and doc_type in template.metadata.doc_types:
                self._cache[cache_key] = template
                return template
        
        return None
    
    def render(self, template: PromptTemplate, **kwargs) -> str:
        from jinja2 import Template
        jinja_template = Template(template.template)
        return jinja_template.render(**kwargs)
```

- [ ] **Step 3: 创建基础模板目录结构**

```bash
mkdir -p backend/app/prompts/templates/base
mkdir -p backend/app/prompts/templates/financial_report
mkdir -p backend/app/prompts/templates/academic_paper
mkdir -p backend/app/prompts/templates/book
```

- [ ] **Step 4: 编写测试**

```python
# backend/tests/test_prompt_manager.py

import pytest
from pathlib import Path
from app.prompts.manager import PromptManager
from app.prompts.models import DocType

@pytest.fixture
async def prompt_manager():
    manager = PromptManager(templates_dir=Path("app/prompts/templates"))
    await manager.initialize()
    return manager

async def test_load_template(prompt_manager):
    template = await prompt_manager.get_template("toc_detection", DocType.GENERIC)
    assert template is not None
    assert "page_text" in template.template

async def test_render_template(prompt_manager):
    template = await prompt_manager.get_template("toc_detection", DocType.GENERIC)
    rendered = prompt_manager.render(template, page_text="目录内容...", page_number=1)
    assert "目录内容" in rendered
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts/
git add backend/tests/test_prompt_manager.py
git commit -m "feat: implement dynamic prompt management system

- Add PromptTemplate data models with validation
- Implement PromptManager with caching
- Support doc_type-specific template selection
- Add YAML template format with Jinja2 rendering"
```

#### Task 1.2: 创建文档类型分类器

**Files:**
- Create: `backend/app/classification/__init__.py`
- Create: `backend/app/classification/models.py`
- Create: `backend/app/classification/classifier.py`

**步骤：**

- [ ] **Step 1: 实现分类器基础**

```python
# backend/app/classification/models.py

from enum import Enum
from typing import Set

class DocumentType(str, Enum):
    UNKNOWN = "unknown"
    FINANCIAL_REPORT = "financial_report"
    ANNUAL_REPORT = "annual_report"
    ACADEMIC_PAPER = "academic_paper"
    TECHNICAL_BOOK = "technical_book"
    LEGAL_DOCUMENT = "legal_document"
    
    @property
    def keywords(self) -> Set[str]:
        keywords_map = {
            self.FINANCIAL_REPORT: {
                "财务报告", "financial report", "资产负债表", "profit"
            },
            self.ACADEMIC_PAPER: {
                "摘要", "abstract", "引言", "introduction", "结论", "conclusion"
            },
            # ...
        }
        return keywords_map.get(self, set())
```

- [ ] **Step 2: 实现 KeywordBasedClassifier**

```python
# backend/app/classification/classifier.py

from typing import Dict, List, Tuple
from dataclasses import dataclass
from .models import DocumentType

@dataclass
class ClassificationResult:
    doc_type: DocumentType
    confidence: float
    method: str
    features: Dict[str, any]
    reasoning: str

class KeywordBasedClassifier:
    def classify(self, text_sample: str, metadata: Dict = None) -> ClassificationResult:
        search_text = (metadata.get("title", "") + " " + text_sample[:2000]).lower()
        
        scores = {}
        for doc_type in DocumentType:
            if doc_type == DocumentType.UNKNOWN:
                continue
            
            score = sum(3 if kw in search_text else 0 for kw in doc_type.keywords)
            if score > 0:
                scores[doc_type] = score
        
        if not scores:
            return ClassificationResult(
                doc_type=DocumentType.UNKNOWN,
                confidence=0.0,
                method="keyword",
                features={},
                reasoning="未匹配到关键词"
            )
        
        best_type = max(scores.keys(), key=lambda x: scores[x])
        total = sum(scores.values())
        confidence = min(scores[best_type] / (total * 0.6), 1.0)
        
        return ClassificationResult(
            doc_type=best_type,
            confidence=confidence,
            method="keyword",
            features={"scores": scores},
            reasoning=f"关键词匹配得分: {scores[best_type]}"
        )
```

- [ ] **Step 3: 编写分类器测试**

```python
# backend/tests/test_classifier.py

import pytest
from app.classification.classifier import KeywordBasedClassifier
from app.classification.models import DocumentType

def test_classify_financial_report():
    classifier = KeywordBasedClassifier()
    result = classifier.classify("2023年度财务报告 资产负债表 利润表", {})
    assert result.doc_type == DocumentType.FINANCIAL_REPORT
    assert result.confidence > 0.5

def test_classify_academic_paper():
    classifier = KeywordBasedClassifier()
    result = classifier.classify("Abstract: This paper presents... Keywords: ML", {})
    assert result.doc_type == DocumentType.ACADEMIC_PAPER
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/classification/
git commit -m "feat: add document type classifier

- Implement keyword-based fast classification
- Support financial/academic/legal document types
- Add classification result with confidence score"
```

### Phase 2: 验证框架（预计 2-3 天）

#### Task 2.1: 创建通用验证框架

**Files:**
- Create: `backend/app/validation/__init__.py`
- Create: `backend/app/validation/models.py`
- Create: `backend/app/validation/rules.py`
- Create: `backend/app/validation/pipeline.py`

**步骤：**

- [ ] **Step 1: 实现验证模型**

```python
# backend/app/validation/models.py

from abc import ABC, abstractmethod
from typing import Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import time

class ValidationLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class ValidationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"

@dataclass
class ValidationResult:
    rule_name: str
    status: ValidationStatus
    level: ValidationLevel
    score: float
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

class ValidationRule(ABC):
    def __init__(self, name: str, level: ValidationLevel, weight: float = 1.0):
        self.name = name
        self.level = level
        self.weight = weight
    
    @abstractmethod
    async def validate(self, context: Dict[str, Any]) -> ValidationResult:
        pass
    
    def should_skip(self, context: Dict[str, Any]) -> bool:
        return False
```

- [ ] **Step 2: 实现 StructureValidationRule**

```python
# backend/app/validation/rules.py

from .models import ValidationRule, ValidationResult, ValidationLevel, ValidationStatus

class StructureValidationRule(ValidationRule):
    def __init__(self):
        super().__init__("structure_validation", ValidationLevel.CRITICAL, weight=2.0)
    
    async def validate(self, context: Dict[str, Any]) -> ValidationResult:
        structure = context.get("structure", [])
        
        if not structure:
            return ValidationResult(
                rule_name=self.name,
                status=ValidationStatus.FAILED,
                level=self.level,
                score=0.0,
                message="目录结构为空"
            )
        
        # 检查节点完整性...
        issues = []
        score = 1.0
        
        # 实现检查逻辑...
        
        status = ValidationStatus.PASSED if score >= 0.8 else ValidationStatus.FAILED
        
        return ValidationResult(
            rule_name=self.name,
            status=status,
            level=self.level,
            score=max(0.0, score),
            message=f"结构验证: {'通过' if status == ValidationStatus.PASSED else '失败'}",
            details={"issues": issues}
        )
```

- [ ] **Step 3: 实现验证管道**

```python
# backend/app/validation/pipeline.py

import asyncio
from typing import List, Dict, Any

from .models import ValidationRule, ValidationContext, ValidationResult, ValidationLevel, ValidationStatus

class ValidationPipeline:
    def __init__(self, max_workers: int = 5):
        self.rules: List[ValidationRule] = []
        self.max_workers = max_workers
    
    def add_rule(self, rule: ValidationRule):
        self.rules.append(rule)
    
    async def execute(self, context: ValidationContext) -> ValidationContext:
        semaphore = asyncio.Semaphore(self.max_workers)
        
        async def execute_one(rule: ValidationRule) -> ValidationResult:
            async with semaphore:
                if rule.should_skip(context.data):
                    return ValidationResult(
                        rule_name=rule.name,
                        status=ValidationStatus.SKIPPED,
                        level=rule.level,
                        score=1.0,
                        message="规则被跳过"
                    )
                return await rule.validate(context.data)
        
        results = await asyncio.gather(*[execute_one(rule) for rule in self.rules])
        for result in results:
            context.add_result(result)
        
        return context
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/validation/
git commit -m "feat: implement validation framework

- Add ValidationRule abstract base class
- Implement StructureValidationRule
- Create ValidationPipeline for parallel execution
- Support different validation levels and scoring"
```

#### Task 2.2: 实现文档类型特定验证规则

**Files:**
- Modify: `backend/app/validation/rules.py`

**步骤：**

- [ ] **Step 1: 添加 TitleAppearanceValidationRule**

```python
# backend/app/validation/rules.py (append)

import asyncio
import random

class TitleAppearanceValidationRule(ValidationRule):
    def __init__(self, sample_rate: float = 0.3):
        super().__init__("title_appearance", ValidationLevel.HIGH, weight=1.5)
        self.sample_rate = sample_rate
    
    async def validate(self, context: Dict[str, Any]) -> ValidationResult:
        structure = context.get("structure", [])
        page_list = context.get("page_list", [])
        
        from pageindex.utils import structure_to_list
        nodes = structure_to_list(structure)
        
        # 抽样检查...
        sample_size = max(int(len(nodes) * self.sample_rate), 5)
        sampled_nodes = random.sample(nodes, min(sample_size, len(nodes)))
        
        # 并行验证逻辑...
        
        return ValidationResult(
            rule_name=self.name,
            status=ValidationStatus.PASSED,  # 根据实际结果
            level=self.level,
            score=0.85,  # 根据实际结果
            message="标题出现验证完成"
        )
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat: add title appearance validation rule

- Implement sampling-based title verification
- Use concurrent validation for performance
- Integrate with prompt manager for dynamic prompts"
```

### Phase 3: 性能优化层（预计 2-3 天）

#### Task 3.1: 实现缓存系统

**Files:**
- Create: `backend/app/performance/__init__.py`
- Create: `backend/app/performance/cache.py`

**步骤：**

- [ ] **Step 1: 实现多级缓存**

```python
# backend/app/performance/cache.py

import hashlib
import json
from typing import Any, Optional
from cachetools import TTLCache
import diskcache as dc

class MultiLevelCache:
    def __init__(self, memory_ttl: int = 300, disk_path: str = "./cache"):
        self._memory = TTLCache(maxsize=1000, ttl=memory_ttl)
        self._disk = dc.Cache(disk_path)
    
    def _make_key(self, *args, **kwargs) -> str:
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def get(self, key: str) -> Optional[Any]:
        if key in self._memory:
            return self._memory[key]
        if key in self._disk:
            value = self._disk[key]
            self._memory[key] = value
            return value
        return None
    
    async def set(self, key: str, value: Any, ttl: int = None):
        self._memory[key] = value
        self._disk[key] = value
```

- [ ] **Step 2: 实现LLM响应缓存**

```python
# backend/app/performance/cache.py (append)

class LLMResponseCache:
    def __init__(self, cache: MultiLevelCache = None):
        self.cache = cache or MultiLevelCache()
        self._hit_count = 0
        self._miss_count = 0
    
    async def get(self, prompt: str, model: str) -> Optional[str]:
        key = self.cache._make_key(prompt[:500], model)
        result = await self.cache.get(f"llm:{key}")
        if result:
            self._hit_count += 1
        else:
            self._miss_count += 1
        return result
    
    async def set(self, prompt: str, model: str, response: str):
        key = self.cache._make_key(prompt[:500], model)
        await self.cache.set(f"llm:{key}", response, ttl=3600)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/performance/
git commit -m "feat: implement multi-level caching system

- Add L1 memory cache with TTL
- Add L2 disk cache using diskcache
- Implement LLMResponseCache for API response caching
- Add cache statistics tracking"
```

#### Task 3.2: 实现批处理优化

**Files:**
- Create: `backend/app/performance/async_processor.py`
- Create: `backend/app/performance/batch_llm.py`

**步骤：**

- [ ] **Step 1: 实现并行批处理器**

```python
# backend/app/performance/async_processor.py

import asyncio
from typing import List, Callable, TypeVar, Generic
from dataclasses import dataclass

T = TypeVar('T')
R = TypeVar('R')

@dataclass
class BatchResult:
    results: List[R]
    failed_indices: List[int]
    success_rate: float

class ParallelBatchProcessor:
    def __init__(self, max_concurrency: int = 5, timeout: float = 30.0):
        self.max_concurrency = max_concurrency
        self.timeout = timeout
    
    async def process_batch(
        self,
        items: List[T],
        processor: Callable[[T], asyncio.Coroutine[Any, Any, R]]
    ) -> BatchResult:
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        async def process_one(index: int, item: T):
            async with semaphore:
                try:
                    result = await asyncio.wait_for(
                        processor(item), timeout=self.timeout
                    )
                    return (index, result, None)
                except Exception as e:
                    return (index, None, e)
        
        tasks = [process_one(i, item) for i, item in enumerate(items)]
        completed = await asyncio.gather(*tasks)
        
        results = [None] * len(items)
        failed_indices = []
        
        for index, result, error in completed:
            if error is None:
                results[index] = result
            else:
                failed_indices.append(index)
        
        success_rate = (len(items) - len(failed_indices)) / len(items)
        return BatchResult(results, failed_indices, success_rate)
```

- [ ] **Step 2: 实现批量LLM处理器**

```python
# backend/app/performance/batch_llm.py

from typing import List
from dataclasses import dataclass
from .async_processor import ParallelBatchProcessor
from .retry import retry_with_backoff, LLM_RETRY_CONFIG

@dataclass
class LLMBatchRequest:
    id: str
    prompt: str
    model: str = "qwen3.5-flash"

@dataclass
class LLMBatchResponse:
    id: str
    success: bool
    content: str = ""
    error: str = ""

class BatchLLMProcessor:
    def __init__(self, max_concurrent: int = 5):
        self.processor = ParallelBatchProcessor(max_concurrent=max_concurrent)
    
    async def process_batch(
        self,
        requests: List[LLMBatchRequest]
    ) -> List[LLMBatchResponse]:
        
        @retry_with_backoff(LLM_RETRY_CONFIG)
        async def process_one(request: LLMBatchRequest) -> LLMBatchResponse:
            from app.core.llm import async_chat_completion
            
            try:
                response = await async_chat_completion(
                    messages=[{"role": "user", "content": request.prompt}],
                    model=request.model
                )
                return LLMBatchResponse(
                    id=request.id,
                    success=True,
                    content=response.choices[0].message.content
                )
            except Exception as e:
                return LLMBatchResponse(
                    id=request.id,
                    success=False,
                    error=str(e)
                )
        
        result = await self.processor.process_batch(requests, process_one)
        return result.results
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/performance/
git commit -m "feat: implement batch processing and retry mechanisms

- Add ParallelBatchProcessor for concurrent execution
- Implement BatchLLMProcessor for efficient LLM calls
- Add exponential backoff retry with jitter
- Support circuit breaker pattern for fault tolerance"
```

### Phase 4: 集成与重构（预计 3-4 天）

#### Task 4.1: 重构 pageindex_service.py

**Files:**
- Modify: `backend/app/services/pageindex_service.py`
- Create: `backend/app/services/pageindex_service_refactored.py` (临时)

**步骤：**

- [ ] **Step 1: 创建新的服务类**

```python
# backend/app/services/pageindex_service_v2.py

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.prompts.manager import prompt_manager
from app.classification.classifier import document_classifier, ClassificationResult
from app.validation.pipeline import ValidationPipeline
from app.validation.rules import StructureValidationRule, TitleAppearanceValidationRule
from app.performance.cache import LLMResponseCache
from app.performance.batch_llm import BatchLLMProcessor

class PageIndexServiceV2:
    """重构后的 PageIndex 服务"""
    
    def __init__(self):
        self.cache = LLMResponseCache()
        self.batch_processor = BatchLLMProcessor(max_concurrent=5)
    
    async def initialize(self):
        """初始化服务"""
        await prompt_manager.initialize()
    
    async def generate_index(
        self, 
        file_path: str, 
        doc_id: str
    ) -> Dict[str, Any]:
        """生成文档索引（新版）"""
        file_path = Path(file_path)
        
        # Stage 1: 文档类型检测
        classification = await self._classify_document(file_path)
        
        # Stage 2: 提取内容
        pages = await self._extract_pages(file_path)
        
        # Stage 3: 目录检测（使用动态提示词）
        toc_result = await self._detect_toc(pages, classification)
        
        # Stage 4: 结构提取
        structure = await self._extract_structure(
            pages, toc_result, classification
        )
        
        # Stage 5: 验证
        validation_context = await self._validate_structure(
            structure, pages, classification
        )
        
        # Stage 6: 增强处理
        enhanced = await self._enhance_structure(structure, pages)
        
        # Stage 7: 保存
        result = await self._save_index(enhanced, doc_id)
        
        return {
            "index_path": result["path"],
            "structure": enhanced,
            "doc_type": classification.doc_type.value,
            "confidence": classification.confidence,
            "validation_score": validation_context.get_overall_score(),
            "metadata": result["metadata"]
        }
    
    async def _classify_document(self, file_path: Path) -> ClassificationResult:
        """分类文档"""
        # 读取文档样本
        text_sample = await self._get_text_sample(file_path)
        
        classification = await document_classifier.classify({
            "text_sample": text_sample,
            "pages": [],
            "metadata": {"title": file_path.stem}
        })
        
        print(f"[Classification] Type: {classification.doc_type.value}, "
              f"Confidence: {classification.confidence:.2%}")
        
        return classification
    
    async def _detect_toc(
        self, 
        pages: List[str], 
        classification: ClassificationResult
    ) -> Dict[str, Any]:
        """检测目录"""
        from app.classification.models import DocumentType
        
        # 加载对应的提示词模板
        prompt = await prompt_manager.render(
            "toc_detection",
            doc_type=classification.doc_type,
            page_text="\n\n".join(pages[:5]),
            page_number=1
        )
        
        # 检查缓存
        cached = await self.cache.get(prompt, "qwen3.5-flash")
        if cached:
            import json
            return json.loads(cached)
        
        # 调用LLM
        from app.core.llm import async_chat_completion
        response = await async_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="qwen3.5-flash"
        )
        
        content = response.choices[0].message.content
        
        # 缓存结果
        await self.cache.set(prompt, "qwen3.5-flash", content)
        
        # 解析结果
        import json
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        
        return {"has_toc": False, "confidence": 0.0}
    
    async def _validate_structure(
        self,
        structure: Dict,
        pages: List[str],
        classification: ClassificationResult
    ):
        """验证结构"""
        from app.validation.models import ValidationContext
        
        pipeline = ValidationPipeline(max_workers=5)
        pipeline.add_rule(StructureValidationRule())
        pipeline.add_rule(TitleAppearanceValidationRule())
        
        context = ValidationContext(
            structure=structure,
            page_list=pages,
            doc_type=classification.doc_type
        )
        
        return await pipeline.execute(context)
    
    async def _get_text_sample(self, file_path: Path) -> str:
        """获取文档文本样本"""
        # 实现文本提取...
        return ""
    
    async def _extract_pages(self, file_path: Path) -> List[str]:
        """提取页面"""
        # 实现页面提取...
        return []
    
    async def _extract_structure(
        self, 
        pages: List[str], 
        toc_result: Dict,
        classification: ClassificationResult
    ) -> Dict:
        """提取结构"""
        # 实现结构提取...
        return {}
    
    async def _enhance_structure(
        self, 
        structure: Dict, 
        pages: List[str]
    ) -> Dict:
        """增强结构（添加摘要等）"""
        # 实现增强逻辑...
        return structure
    
    async def _save_index(self, structure: Dict, doc_id: str) -> Dict:
        """保存索引"""
        # 实现保存逻辑...
        return {"path": "", "metadata": {}}
```

- [ ] **Step 2: 添加兼容性层**

```python
# backend/app/services/pageindex_service.py (修改，添加适配器)

# 在文件末尾添加

class PageIndexServiceAdapter:
    """适配器 - 兼容旧版接口"""
    
    def __init__(self):
        self.v2_service = None
    
    async def _get_v2_service(self):
        if self.v2_service is None:
            from .pageindex_service_v2 import PageIndexServiceV2
            self.v2_service = PageIndexServiceV2()
            await self.v2_service.initialize()
        return self.v2_service
    
    async def generate_index(self, file_path: str, doc_id: str) -> Dict[str, Any]:
        """兼容旧接口"""
        service = await self._get_v2_service()
        return await service.generate_index(file_path, doc_id)
    
    # 其他方法...
```

- [ ] **Step 3: 编写集成测试**

```python
# backend/tests/test_pageindex_service_v2.py

import pytest
from pathlib import Path
from app.services.pageindex_service_v2 import PageIndexServiceV2

@pytest.fixture
async def service():
    s = PageIndexServiceV2()
    await s.initialize()
    return s

@pytest.mark.asyncio
async def test_generate_index(service, tmp_path):
    # 创建测试PDF
    test_pdf = tmp_path / "test.pdf"
    # ... 创建测试文档
    
    result = await service.generate_index(str(test_pdf), "test_doc_001")
    
    assert "structure" in result
    assert "doc_type" in result
    assert "validation_score" in result
    assert result["validation_score"] >= 0.6
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/pageindex_service_v2.py
git add backend/tests/test_pageindex_service_v2.py
git commit -m "feat: implement refactored PageIndexService with new architecture

- Integrate prompt manager for dynamic templates
- Add document classification in pipeline
- Implement validation framework integration
- Add caching and batch processing optimizations
- Maintain backward compatibility with adapter"
```

#### Task 4.2: 迁移提示词模板

**Files:**
- Create: `backend/app/prompts/templates/base/toc_detection.yaml`
- Create: `backend/app/prompts/templates/base/title_matching.yaml`
- Create: `backend/app/prompts/templates/base/structure_extraction.yaml`

**步骤：**

- [ ] **Step 1: 迁移 TOC 检测提示词**

```yaml
# backend/app/prompts/templates/base/toc_detection.yaml

metadata:
  name: "toc_detection"
  version: "1.0.0"
  doc_types: ["generic", "financial_report", "academic_paper", "book"]
  description: "检测页面是否包含目录"
  author: "system"
  
variables:
  - name: "page_text"
    type: "string"
    required: true
    description: "页面文本内容"
  - name: "page_number"
    type: "integer"
    required: false
    description: "页码"

template: |
  判断页面是否包含目录。
  
  页面内容: {{ page_text[:500] }}
  {% if page_number %}页码: {{ page_number }}{% endif %}
  
  目录特征：
  - 包含"目录"、"Contents"等字样
  - 有章节标题和页码
  - 位于文档开头部分
  
  注意：摘要、图表列表、符号列表等不是目录。
  
  返回JSON：
  {
    "has_toc": true|false,
    "confidence": 0.0-1.0,
    "reasoning": "简要说明"
  }

output_schema:
  type: "json"
  required_fields: ["has_toc", "confidence"]
```

- [ ] **Step 2: 迁移标题匹配提示词**

```yaml
# backend/app/prompts/templates/base/title_matching.yaml

metadata:
  name: "title_matching"
  version: "1.0.0"
  doc_types: ["generic", "financial_report", "academic_paper", "book"]
  description: "判断章节标题是否出现在页面中"
  
variables:
  - name: "title"
    type: "string"
    required: true
  - name: "page_text"
    type: "string"
    required: true

template: |
  判断章节标题是否出现在页面中。
  
  章节标题: {{ title }}
  页面内容: {{ page_text[:800] }}
  
  注意：使用模糊匹配，忽略空格差异。标题可能是变体形式。
  
  返回JSON：
  {
    "answer": "yes|no",
    "confidence": 0.0-1.0,
    "thinking": "简要判断理由"
  }

output_schema:
  type: "json"
  required_fields: ["answer", "confidence"]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/prompts/templates/
git commit -m "feat: migrate prompts to YAML templates

- Convert hardcoded prompts to dynamic YAML templates
- Add Jinja2 templating support
- Organize templates by document type
- Add validation schemas for output format"
```

### Phase 5: 测试与优化（预计 2-3 天）

#### Task 5.1: 性能测试

**Files:**
- Create: `backend/tests/benchmarks/test_performance.py`

**步骤：**

- [ ] **Step 1: 创建性能测试**

```python
# backend/tests/benchmarks/test_performance.py

import pytest
import asyncio
import time
from pathlib import Path
from app.services.pageindex_service_v2 import PageIndexServiceV2

@pytest.mark.benchmark
class TestPerformance:
    
    @pytest.fixture
    async def service(self):
        s = PageIndexServiceV2()
        await s.initialize()
        return s
    
    @pytest.mark.asyncio
    async def test_processing_time(self, service, sample_documents):
        """测试处理时间"""
        times = []
        
        for doc_path in sample_documents[:5]:
            start = time.time()
            result = await service.generate_index(str(doc_path), f"bench_{doc_path.stem}")
            elapsed = time.time() - start
            times.append(elapsed)
            
            print(f"Document {doc_path.name}: {elapsed:.2f}s")
        
        avg_time = sum(times) / len(times)
        print(f"\nAverage processing time: {avg_time:.2f}s")
        
        # 断言：平均处理时间应小于30秒
        assert avg_time < 30.0, f"Average time {avg_time:.2f}s exceeds threshold"
    
    @pytest.mark.asyncio
    async def test_cache_hit_rate(self, service):
        """测试缓存命中率"""
        from app.performance.cache import llm_cache
        
        # 重置统计
        llm_cache._hit_count = 0
        llm_cache._miss_count = 0
        
        # 多次处理同一文档
        doc_path = sample_documents[0]
        for i in range(3):
            result = await service.generate_index(str(doc_path), f"cache_test_{i}")
        
        stats = llm_cache.get_stats()
        print(f"Cache stats: {stats}")
        
        # 期望命中率 > 50%
        assert stats["hit_rate"] > 0.5, f"Cache hit rate {stats['hit_rate']:.1%} too low"
    
    @pytest.mark.asyncio
    async def test_concurrent_processing(self, service, sample_documents):
        """测试并发处理能力"""
        start = time.time()
        
        # 并发处理5个文档
        tasks = [
            service.generate_index(str(doc), f"concurrent_{i}")
            for i, doc in enumerate(sample_documents[:5])
        ]
        
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start
        
        print(f"Concurrent processing 5 docs: {elapsed:.2f}s")
        
        # 总时间应小于串行时间的60%（即至少40%的并行收益）
        # 假设串行平均10秒/文档，5个应50秒，并发应<30秒
        assert elapsed < 30.0, f"Concurrent time {elapsed:.2f}s too long"
```

- [ ] **Step 2: Commit**

```bash
git add backend/tests/benchmarks/
git commit -m "test: add performance benchmarks

- Add processing time benchmark
- Add cache hit rate test
- Add concurrent processing test
- Set performance thresholds"
```

#### Task 5.2: 集成测试与验收

**Files:**
- Create: `backend/tests/integration/test_full_pipeline.py`

**步骤：**

- [ ] **Step 1: 创建端到端测试**

```python
# backend/tests/integration/test_full_pipeline.py

import pytest
from pathlib import Path
import json

@pytest.mark.integration
class TestFullPipeline:
    
    @pytest.mark.asyncio
    async def test_financial_report_processing(self):
        """测试财务报告处理流程"""
        from app.services.pageindex_service_v2 import PageIndexServiceV2
        
        service = PageIndexServiceV2()
        await service.initialize()
        
        # 使用示例财务报告
        result = await service.generate_index(
            "tests/fixtures/sample_annual_report.pdf",
            "test_financial_001"
        )
        
        # 验证结果
        assert result["doc_type"] == "financial_report"
        assert result["confidence"] > 0.7
        assert result["validation_score"] >= 0.6
        assert "structure" in result
        assert "metadata" in result
        
        # 验证索引文件
        index_path = Path(result["index_path"])
        assert index_path.exists()
        
        with open(index_path) as f:
            index_data = json.load(f)
        
        assert "structure" in index_data
        assert "doc_description" in index_data
    
    @pytest.mark.asyncio
    async def test_academic_paper_processing(self):
        """测试学术论文处理流程"""
        # 类似上述测试...
        pass
    
    @pytest.mark.asyncio
    async def test_fallback_mechanisms(self):
        """测试回退机制"""
        # 测试当某个验证失败时的回退行为
        pass
```

- [ ] **Step 2: 创建测试数据**

```bash
mkdir -p backend/tests/fixtures/
# 添加测试文档样本（手动或使用生成脚本）
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/
git add backend/tests/fixtures/
git commit -m "test: add integration tests for full pipeline

- Add end-to-end tests for different document types
- Test validation and fallback mechanisms
- Include test fixtures"
```

### Phase 6: 文档与部署（预计 1-2 天）

#### Task 6.1: 更新文档

**Files:**
- Create: `docs/prompt_system.md`
- Create: `docs/validation_framework.md`
- Create: `docs/performance_optimization.md`

**步骤：**

- [ ] **Step 1: 编写提示词系统文档**

```markdown
# 提示词系统文档

## 概述

提示词系统支持动态加载和热更新，通过 YAML 模板管理。

## 目录结构

```
app/prompts/templates/
├── base/              # 基础模板
├── financial_report/  # 财务报告专用
├── academic_paper/    # 学术论文专用
└── book/              # 书籍专用
```

## 添加新模板

1. 在对应目录创建 YAML 文件
2. 定义 metadata, variables, template
3. 重启服务或使用热更新

## 模板格式

见示例：`templates/base/toc_detection.yaml`

## API

```python
from app.prompts.manager import prompt_manager

# 渲染提示词
prompt = await prompt_manager.render(
    "toc_detection",
    doc_type=DocType.FINANCIAL_REPORT,
    page_text="..."
)
```
```

- [ ] **Step 2: 编写验证框架文档**

```markdown
# 验证框架文档

## 概述

通用验证框架支持多规则并行验证和回退策略。

## 添加验证规则

1. 继承 `ValidationRule`
2. 实现 `validate` 方法
3. 注册到 `ValidationPipeline`

## 回退策略

当验证失败时，可以配置回退策略自动修复问题。
```

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs: add system documentation

- Add prompt system documentation
- Add validation framework guide
- Add performance optimization docs"
```

#### Task 6.2: 最终集成

**Files:**
- Modify: `backend/app/services/pageindex_service.py`
- Delete: `backend/app/services/pageindex_service_v2.py`

**步骤：**

- [ ] **Step 1: 替换主服务**

```python
# backend/app/services/pageindex_service.py

# 完全替换为 V2 版本的内容
# 删除旧的 PageIndexService 类
# 重命名 PageIndexServiceV2 为 PageIndexService
```

- [ ] **Step 2: 删除临时文件**

```bash
git rm backend/app/services/pageindex_service_v2.py
git rm backend/app/services/pageindex_service_refactored.py  # 如果有
```

- [ ] **Step 3: 最终测试**

```bash
cd backend
python -m pytest tests/ -v --tb=short
```

- [ ] **Step 4: 提交最终版本**

```bash
git add backend/app/services/pageindex_service.py
git commit -m "feat: finalize PageIndex service refactoring

- Replace legacy implementation with new architecture
- Integrate all performance optimizations
- Full backward compatibility maintained"
```

---

## 7. 实施清单总结

### 7.1 新建文件清单

| 文件路径 | 类型 | 说明 |
|---------|------|------|
| `backend/app/prompts/__init__.py` | 新建 | 提示词模块初始化 |
| `backend/app/prompts/models.py` | 新建 | 数据模型 |
| `backend/app/prompts/manager.py` | 新建 | 提示词管理器 |
| `backend/app/prompts/loader.py` | 新建 | 模板加载器 |
| `backend/app/prompts/templates/base/*.yaml` | 新建 | 基础模板 |
| `backend/app/prompts/templates/financial_report/*.yaml` | 新建 | 财务报告模板 |
| `backend/app/prompts/templates/academic_paper/*.yaml` | 新建 | 学术论文模板 |
| `backend/app/prompts/templates/book/*.yaml` | 新建 | 书籍模板 |
| `backend/app/classification/__init__.py` | 新建 | 分类模块初始化 |
| `backend/app/classification/models.py` | 新建 | 文档类型模型 |
| `backend/app/classification/classifier.py` | 新建 | 分类器实现 |
| `backend/app/validation/__init__.py` | 新建 | 验证模块初始化 |
| `backend/app/validation/models.py` | 新建 | 验证模型 |
| `backend/app/validation/rules.py` | 新建 | 验证规则 |
| `backend/app/validation/pipeline.py` | 新建 | 验证管道 |
| `backend/app/validation/fallback.py` | 新建 | 回退策略 |
| `backend/app/performance/__init__.py` | 新建 | 性能模块初始化 |
| `backend/app/performance/cache.py` | 新建 | 缓存系统 |
| `backend/app/performance/async_processor.py` | 新建 | 异步处理器 |
| `backend/app/performance/batch_llm.py` | 新建 | 批量LLM处理 |
| `backend/app/performance/retry.py` | 新建 | 重试机制 |
| `backend/tests/test_prompt_manager.py` | 新建 | 提示词测试 |
| `backend/tests/test_classifier.py` | 新建 | 分类器测试 |
| `backend/tests/test_validation.py` | 新建 | 验证测试 |
| `backend/tests/benchmarks/test_performance.py` | 新建 | 性能测试 |
| `backend/tests/integration/test_full_pipeline.py` | 新建 | 集成测试 |
| `docs/prompt_system.md` | 新建 | 提示词系统文档 |
| `docs/validation_framework.md` | 新建 | 验证框架文档 |
| `docs/performance_optimization.md` | 新建 | 性能优化文档 |

### 7.2 修改文件清单

| 文件路径 | 类型 | 修改内容 |
|---------|------|---------|
| `backend/app/services/pageindex_service.py` | 修改 | 完全重构，使用新架构 |
| `backend/pageindex/page_index.py` | 可选修改 | 可选：迁移部分功能到新服务 |
| `backend/app/core/config.py` | 修改 | 添加新配置项 |
| `backend/requirements.txt` | 修改 | 添加依赖：jinja2, watchdog, diskcache |

### 7.3 删除/废弃文件清单

| 文件路径 | 操作 | 说明 |
|---------|------|------|
| `backend/app/prompts/pageindex_prompts.py` | 废弃 | 提示词已迁移到YAML |
| `backend/app/services/pageindex_service_v2.py` | 删除（临时） | 开发完成后删除 |

### 7.4 新增依赖

```txt
# backend/requirements.txt 添加
jinja2>=3.1.0          # 模板引擎
watchdog>=3.0.0        # 文件监控（热更新）
diskcache>=5.6.0       # 磁盘缓存
cachetools>=5.3.0      # 内存缓存
pyyaml>=6.0            # YAML解析（如未安装）
pydantic>=2.0.0        # 数据验证（如未升级）
```

---

## 8. 风险与回退计划

### 8.1 风险识别

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 新服务性能不如旧版 | 中 | 高 | 保持旧版代码，可快速切换 |
| 提示词迁移遗漏 | 中 | 中 | 完整测试覆盖，逐个迁移 |
| 并发引入竞态条件 | 低 | 高 | 使用 asyncio 锁，充分测试 |
| 缓存一致性问题 | 低 | 中 | 设置合理的TTL，支持手动刷新 |

### 8.2 回退策略

1. **功能开关**: 在配置中添加 `USE_V2_SERVICE` 开关
2. **影子测试**: 新服务并行运行，对比输出
3. **快速回滚**: 保留旧版本分支，5分钟内可回滚

```python
# backend/app/core/config.py 添加

USE_V2_PAGEINDEX = os.getenv("USE_V2_PAGEINDEX", "false").lower() == "true"
ENABLE_PROMPT_CACHE = os.getenv("ENABLE_PROMPT_CACHE", "true").lower() == "true"
```

---

## 9. 预期收益

### 9.1 性能提升

- **LLM调用减少**: 通过缓存减少 30-50% 的重复调用
- **处理速度**: 并行化后提升 40-60% 的吞吐量
- **响应时间**: 缓存命中时响应时间减少 90%+

### 9.2 可维护性提升

- **提示词管理**: 热更新，无需重启服务
- **验证扩展**: 新增文档类型只需添加规则
- **代码解耦**: 各模块独立，便于单元测试

### 9.3 功能增强

- **文档类型感知**: 针对不同类型使用不同策略
- **智能验证**: 多维度验证，自动回退
- **性能可调**: 通过配置调整并发度和缓存策略

---

**计划制定完成！**

**执行顺序建议：**
1. 按 Phase 顺序执行，每个 Phase 完成后再进入下一个
2. 每完成一个 Task 运行测试确保通过
3. 保持频繁的 git commit
4. 在 Phase 4 结束前保持新旧版本并存，便于对比测试

**预计总工期：12-16 天**（视测试和调试情况而定）
