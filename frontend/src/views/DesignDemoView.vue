<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  CheckSquare2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Eye,
  FileArchive,
  FileCode,
  FileSpreadsheet,
  FileText,
  FileType,
  Folder,
  FolderOpen,
  Grid2X2,
  List,
  MoreHorizontal,
  Presentation,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Square,
  Upload,
  X,
} from 'lucide-vue-next'

type ViewMode = 'list' | 'grid'

const viewMode = ref<ViewMode>('list')
const activeFolderId = ref('strategy')
const selectedDocId = ref('market-report')
const previewOpen = ref(true)
const currentDocPage = ref(1)
const totalDocPages = 6
const batchMode = ref(false)
const pageSize = 6
const selectedBatchIds = ref(['market-report', 'forecast-model'])

const folders = [
  { id: 'all', name: '全部文档', count: 128, icon: FolderOpen },
  { id: 'strategy', name: '战略资料', count: 26, icon: Folder },
  { id: 'contracts', name: '合同归档', count: 18, icon: Folder },
  { id: 'finance', name: '财务分析', count: 14, icon: Folder },
  { id: 'research', name: '用户研究', count: 42, icon: Folder },
]

const documents = [
  {
    id: 'market-report',
    name: '2026 市场进入策略报告.pdf',
    type: 'PDF',
    status: '已完成',
    pages: 84,
    words: '46,820',
    size: '12.4 MB',
    folder: '战略资料',
    updatedAt: '8 分钟前',
    uploadedAt: '2026-06-08 14:22',
    owner: 'admin',
    indexMode: '智能',
    duration: '2 分 18 秒',
    lastIndexedAt: '8 分钟前',
    tocNodes: 32,
    summaryCoverage: '94%',
    textChars: '118,430',
    ocrPages: 9,
    warnings: 0,
    summary: '包含目标市场判断、渠道优先级、区域推进节奏和风险应对策略。',
    progress: 100,
  },
  {
    id: 'pipeline-review',
    name: '销售管线风险复盘.docx',
    type: 'DOCX',
    status: '索引中',
    pages: 31,
    words: '18,360',
    size: '4.8 MB',
    folder: '战略资料',
    updatedAt: '22 分钟前',
    uploadedAt: '2026-06-10 09:18',
    owner: 'admin',
    indexMode: '均衡',
    duration: '进行中',
    lastIndexedAt: '22 分钟前',
    tocNodes: 14,
    summaryCoverage: '62%',
    textChars: '52,900',
    ocrPages: 0,
    warnings: 1,
    summary: '按负责人整理本周阻塞项、合同推进状态和需要管理层介入的问题。',
    progress: 68,
  },
  {
    id: 'forecast-model',
    name: '区域收入预测模型.xlsx',
    type: 'XLSX',
    status: '已完成',
    pages: 12,
    words: '8,940',
    size: '2.1 MB',
    folder: '财务分析',
    updatedAt: '45 分钟前',
    uploadedAt: '2026-06-09 17:04',
    owner: 'finance',
    indexMode: '快速',
    duration: '41 秒',
    lastIndexedAt: '45 分钟前',
    tocNodes: 8,
    summaryCoverage: '88%',
    textChars: '27,610',
    ocrPages: 0,
    warnings: 0,
    summary: '收入敏感性模型，包含区域假设、转化率曲线和置信区间。',
    progress: 100,
  },
  {
    id: 'interview-cluster',
    name: '用户访谈纪要合集.txt',
    type: 'TXT',
    status: '已完成',
    pages: 146,
    words: '92,500',
    size: '8.6 MB',
    folder: '用户研究',
    updatedAt: '2 小时前',
    uploadedAt: '2026-06-07 11:30',
    owner: 'research',
    indexMode: '智能',
    duration: '3 分 05 秒',
    lastIndexedAt: '2 小时前',
    tocNodes: 46,
    summaryCoverage: '97%',
    textChars: '211,360',
    ocrPages: 0,
    warnings: 0,
    summary: '按需求强度和异议类型聚类后的客户原声材料。',
    progress: 100,
  },
  {
    id: 'contract-terms',
    name: '年度服务合同条款汇总.pdf',
    type: 'PDF',
    status: '已完成',
    pages: 58,
    words: '31,240',
    size: '7.3 MB',
    folder: '合同归档',
    updatedAt: '3 小时前',
    uploadedAt: '2026-06-06 15:42',
    owner: 'legal',
    indexMode: '均衡',
    duration: '1 分 32 秒',
    lastIndexedAt: '3 小时前',
    tocNodes: 21,
    summaryCoverage: '91%',
    textChars: '86,710',
    ocrPages: 4,
    warnings: 0,
    summary: '归纳服务范围、验收标准、违约责任和续约条款差异。',
    progress: 100,
  },
  {
    id: 'support-faq',
    name: '客服高频问题知识库.md',
    type: 'TXT',
    status: '已完成',
    pages: 38,
    words: '22,780',
    size: '1.6 MB',
    folder: '用户研究',
    updatedAt: '4 小时前',
    uploadedAt: '2026-06-06 10:08',
    owner: 'support',
    indexMode: '快速',
    duration: '29 秒',
    lastIndexedAt: '4 小时前',
    tocNodes: 18,
    summaryCoverage: '93%',
    textChars: '64,210',
    ocrPages: 0,
    warnings: 0,
    summary: '整理客服问答、处理路径、升级条件和标准回复素材。',
    progress: 100,
  },
  {
    id: 'board-pack',
    name: '董事会经营简报.pptx',
    type: 'PPTX',
    status: '已完成',
    pages: 42,
    words: '15,620',
    size: '9.8 MB',
    folder: '战略资料',
    updatedAt: '昨天',
    uploadedAt: '2026-06-05 18:20',
    owner: 'admin',
    indexMode: '智能',
    duration: '1 分 47 秒',
    lastIndexedAt: '昨天',
    tocNodes: 19,
    summaryCoverage: '90%',
    textChars: '44,500',
    ocrPages: 12,
    warnings: 0,
    summary: '覆盖经营指标、收入结构、产品进展和下季度资源诉求。',
    progress: 100,
  },
  {
    id: 'compliance-checklist',
    name: '合规检查清单.csv',
    type: 'XLSX',
    status: '已完成',
    pages: 9,
    words: '6,100',
    size: '0.9 MB',
    folder: '合同归档',
    updatedAt: '昨天',
    uploadedAt: '2026-06-05 09:36',
    owner: 'legal',
    indexMode: '快速',
    duration: '18 秒',
    lastIndexedAt: '昨天',
    tocNodes: 6,
    summaryCoverage: '84%',
    textChars: '19,820',
    ocrPages: 0,
    warnings: 0,
    summary: '按检查项、责任人、证据材料和整改状态整理合规进展。',
    progress: 100,
  },
]

const toc = [
  {
    id: 'toc-1',
    title: '1. 执行摘要',
    page: 1,
    summary: '概括市场窗口、推荐进入节奏和前三个季度的关键里程碑。',
    children: [
      { id: 'toc-1-1', title: '1.1 核心结论', page: 2, summary: '增长机会集中在企业知识管理和合规问答两个场景。' },
      { id: 'toc-1-2', title: '1.2 关键风险', page: 4, summary: '主要风险来自渠道教育成本、竞品价格下探和上线周期不确定。' },
    ],
  },
  {
    id: 'toc-2',
    title: '2. 市场与客户分层',
    page: 9,
    summary: '按行业、组织规模和采购成熟度划分目标客户优先级。',
    children: [
      { id: 'toc-2-1', title: '2.1 行业优先级', page: 13, summary: '金融、制造和专业服务在资料密度与合规压力上最匹配。' },
      { id: 'toc-2-2', title: '2.2 采购触发因素', page: 18, summary: '知识库迁移、审计整改和客服降本是最常见触发点。' },
    ],
  },
  {
    id: 'toc-3',
    title: '3. 渠道推进计划',
    page: 31,
    summary: '定义伙伴分层、试点包、售前材料和区域节奏。',
    children: [
      { id: 'toc-3-1', title: '3.1 伙伴分层', page: 35, summary: '一线伙伴负责行业样板，二线伙伴负责区域覆盖和交付。' },
      { id: 'toc-3-2', title: '3.2 试点包设计', page: 42, summary: '试点包控制在两周内交付，输出检索命中率和业务问答样例。' },
    ],
  },
]

const selectedDocument = computed(() => documents.find((doc) => doc.id === selectedDocId.value) ?? documents[0])
const visibleDocuments = computed(() => documents.slice(0, pageSize))

function toggleBatchSelect(id: string) {
  selectedBatchIds.value = selectedBatchIds.value.includes(id)
    ? selectedBatchIds.value.filter((item) => item !== id)
    : [...selectedBatchIds.value, id]
}

function docIcon(type: string) {
  if (type === 'DOCX') return FileType
  if (type === 'XLSX') return FileSpreadsheet
  if (type === 'TXT') return FileCode
  if (type === 'PPTX') return Presentation
  if (type === 'CSV') return FileSpreadsheet
  if (type === 'ARCHIVE') return FileArchive
  return FileText
}

function fileKindClass(type: string) {
  if (type === 'PDF') return 'pdf'
  if (type === 'DOCX') return 'word'
  if (type === 'XLSX' || type === 'CSV') return 'sheet'
  if (type === 'PPTX') return 'slide'
  if (type === 'TXT') return 'text'
  return 'default'
}
</script>

<template>
  <div class="demo-page">
    <main class="workbench">
      <header class="topbar">
        <div class="topbar-title">
          <button class="icon-text">
            <ArrowLeft class="h-4 w-4" />
            <span>返回主界面</span>
          </button>
          <div>
            <p>Documents</p>
            <h1>文档管理工作台</h1>
          </div>
        </div>

        <div class="topbar-actions">
          <label class="search-box">
            <Search class="h-4 w-4" />
            <span>搜索文档、文件夹或标签</span>
          </label>
          <button class="primary-btn">
            <Upload class="h-4 w-4" />
            <span>上传文档</span>
          </button>
        </div>
      </header>

      <section class="documents-layout">
        <aside class="surface folder-pane">
          <div class="surface-head">
            <div>
              <p>文件夹</p>
              <h2>资料库</h2>
            </div>
            <button class="icon-btn" aria-label="folder more">
              <MoreHorizontal class="h-4 w-4" />
            </button>
          </div>

          <div class="folder-list">
            <button
              v-for="folder in folders"
              :key="folder.id"
              :class="{ active: activeFolderId === folder.id }"
              @click="activeFolderId = folder.id"
            >
              <component :is="folder.icon" class="h-4 w-4" />
              <span>{{ folder.name }}</span>
              <em>{{ folder.count }}</em>
            </button>
          </div>
        </aside>

        <section class="surface doc-pane">
          <div class="surface-head doc-head">
            <div>
              <p>当前位置 / 战略资料</p>
              <h2>全部文档</h2>
            </div>
            <div class="doc-tools">
              <button class="tool-btn">
                <SlidersHorizontal class="h-4 w-4" />
                <span>更新时间</span>
              </button>
              <button :class="['tool-btn', { active: batchMode }]" @click="batchMode = !batchMode">
                <CheckSquare2 v-if="batchMode" class="h-4 w-4" />
                <Square v-else class="h-4 w-4" />
                <span>批量</span>
              </button>
              <div class="view-toggle">
                <button :class="{ active: viewMode === 'list' }" aria-label="list" @click="viewMode = 'list'">
                  <List class="h-4 w-4" />
                </button>
                <button :class="{ active: viewMode === 'grid' }" aria-label="grid" @click="viewMode = 'grid'">
                  <Grid2X2 class="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>

          <div v-if="batchMode" class="mode-strip batch-strip">
            <span>已选择 {{ selectedBatchIds.length }} 项</span>
            <button @click="selectedBatchIds = visibleDocuments.map((doc) => doc.id)">全选本页</button>
            <button @click="selectedBatchIds = []">取消选择</button>
            <button>移动</button>
            <button>重新解析</button>
            <button>删除</button>
          </div>
          <div v-else class="mode-strip list-insight">
            <span>当前文件夹 26 个文档</span>
            <em>最近更新 8 分钟前</em>
            <em>1 个索引任务进行中</em>
          </div>

          <div :class="['doc-scroll', { scrollable: batchMode }]">
            <div v-if="viewMode === 'list'" class="doc-list">
              <div class="doc-list-header">
                <span>文档</span>
                <span>摘要</span>
                <span>状态</span>
                <span>更新</span>
                <span>操作</span>
              </div>
              <button
                v-for="doc in visibleDocuments"
                :key="doc.id"
                :class="{ active: selectedDocId === doc.id, batch: batchMode }"
                @click="selectedDocId = doc.id"
              >
                <div class="doc-file-cell">
                  <span
                    :class="['row-check', { checked: selectedBatchIds.includes(doc.id), hidden: !batchMode }]"
                    @click.stop="batchMode && toggleBatchSelect(doc.id)"
                  >
                    <CheckSquare2 v-if="selectedBatchIds.includes(doc.id)" class="h-4 w-4" />
                    <Square v-else class="h-4 w-4" />
                  </span>
                  <div :class="['doc-icon', fileKindClass(doc.type)]">
                    <component :is="docIcon(doc.type)" class="h-4 w-4" />
                  </div>
                  <div>
                    <strong>{{ doc.name }}</strong>
                    <span>{{ doc.folder }} / {{ doc.type }} / {{ doc.size }}</span>
                  </div>
                </div>
                <p class="doc-summary-cell">{{ doc.summary }}</p>
                <div class="doc-status-cell">
                  <span :class="['status', doc.status === '已完成' ? 'done' : 'running']">{{ doc.status }}</span>
                  <em>{{ doc.pages }} 页</em>
                </div>
                <div class="doc-meta">
                  <span>{{ doc.updatedAt }}</span>
                  <em>{{ doc.owner }}</em>
                </div>
                <div class="row-actions">
                  <button title="打开预览" @click.stop="previewOpen = true">
                    <Eye class="h-4 w-4" />
                  </button>
                  <button title="重新解析" @click.stop>
                    <RefreshCw class="h-4 w-4" />
                  </button>
                  <button title="更多" @click.stop>
                    <MoreHorizontal class="h-4 w-4" />
                  </button>
                </div>
              </button>
            </div>

            <div v-else class="doc-grid">
              <button
                v-for="doc in visibleDocuments"
                :key="doc.id"
                :class="{ active: selectedDocId === doc.id }"
                @click="selectedDocId = doc.id"
              >
                <div class="card-line">
                  <span
                    :class="['row-check', { checked: selectedBatchIds.includes(doc.id), hidden: !batchMode }]"
                    @click.stop="batchMode && toggleBatchSelect(doc.id)"
                  >
                    <CheckSquare2 v-if="selectedBatchIds.includes(doc.id)" class="h-4 w-4" />
                    <Square v-else class="h-4 w-4" />
                  </span>
                  <div :class="['doc-icon', fileKindClass(doc.type)]">
                    <component :is="docIcon(doc.type)" class="h-4 w-4" />
                  </div>
                  <span :class="['status', doc.status === '已完成' ? 'done' : 'running']">{{ doc.status }}</span>
                </div>
                <strong>{{ doc.name }}</strong>
                <p>{{ doc.summary }}</p>
              </button>
            </div>
          </div>

          <footer class="pagination">
            <div>
              <strong>第 {{ currentDocPage }} 页</strong>
              <span>每页 {{ pageSize }} 个 / 共 128 个文档 / {{ totalDocPages }} 页</span>
            </div>
            <div class="page-controls">
              <button :disabled="currentDocPage === 1" @click="currentDocPage = Math.max(1, currentDocPage - 1)">
                上一页
              </button>
              <button
                v-for="page in [1, 2, 3, 4]"
                :key="page"
                :class="{ active: currentDocPage === page }"
                @click="currentDocPage = page"
              >
                {{ page }}
              </button>
              <span>...</span>
              <button :class="{ active: currentDocPage === totalDocPages }" @click="currentDocPage = totalDocPages">
                {{ totalDocPages }}
              </button>
              <button :disabled="currentDocPage === totalDocPages" @click="currentDocPage = Math.min(totalDocPages, currentDocPage + 1)">
                下一页
              </button>
            </div>
          </footer>
        </section>

        <aside class="surface detail-pane">
          <div class="surface-head">
            <div>
              <p>文档详情</p>
            </div>
          </div>

          <div class="detail-identity">
            <div :class="['detail-icon', fileKindClass(selectedDocument.type)]">
              <component :is="docIcon(selectedDocument.type)" class="h-5 w-5" />
            </div>
            <div>
              <h3>{{ selectedDocument.name }}</h3>
              <span>{{ selectedDocument.folder }} / {{ selectedDocument.type }} / {{ selectedDocument.size }}</span>
            </div>
          </div>

          <div class="detail-section basic-detail">
            <div class="section-title">
              <FileText class="h-4 w-4" />
              <h4>基础属性</h4>
            </div>
            <div class="property-list">
              <div><span>上传人</span><strong>{{ selectedDocument.owner }}</strong></div>
              <div><span>上传时间</span><strong>{{ selectedDocument.uploadedAt }}</strong></div>
              <div><span>更新时间</span><strong>{{ selectedDocument.updatedAt }}</strong></div>
              <div><span>页数 / 字数</span><strong>{{ selectedDocument.pages }} 页 / {{ selectedDocument.words }}</strong></div>
            </div>
          </div>

          <div class="detail-section index-detail">
            <div class="section-title">
              <RefreshCw class="h-4 w-4" />
              <h4>索引状态</h4>
            </div>
            <div class="status-panel">
              <div class="status-line">
                <span :class="['status', selectedDocument.status === '已完成' ? 'done' : 'running']">
                  {{ selectedDocument.status }}
                </span>
                <em>{{ selectedDocument.indexMode }} / {{ selectedDocument.duration }} / 最近 {{ selectedDocument.lastIndexedAt }}</em>
              </div>
              <div class="progress-track">
                <i :style="{ width: `${selectedDocument.progress}%` }"></i>
              </div>
            </div>
            <div class="quality-grid">
              <div>
                <span>TOC 节点</span>
                <strong>{{ selectedDocument.tocNodes }}</strong>
              </div>
              <div>
                <span>摘要覆盖</span>
                <strong>{{ selectedDocument.summaryCoverage }}</strong>
              </div>
              <div>
                <span>文本字符</span>
                <strong>{{ selectedDocument.textChars }}</strong>
              </div>
              <div>
                <span>OCR 页</span>
                <strong>{{ selectedDocument.ocrPages }}</strong>
              </div>
            </div>
            <div :class="['quality-note', selectedDocument.warnings > 0 ? 'warning' : 'ok']">
              <CheckCircle2 v-if="selectedDocument.warnings === 0" class="h-4 w-4" />
              <CircleDashed v-else class="h-4 w-4" />
              <span>
                {{ selectedDocument.warnings === 0 ? '索引可用于问答和引用定位' : `${selectedDocument.warnings} 个解析警告，建议复核后重建索引` }}
              </span>
            </div>
          </div>

          <div class="detail-section summary-detail">
            <div class="section-title">
              <Sparkles class="h-4 w-4" />
              <h4>全文摘要</h4>
            </div>
            <div class="summary-scroll">
              <p>{{ selectedDocument.summary }} 该摘要用于快速判断文档是否值得打开查看。实际接入时，如果后端返回的全文摘要更长，这一区域内部滚动，不会把右侧详情面板撑出页面。摘要区域会优先占用详情页下方剩余空间，让右侧页面更饱满，同时不影响上方关键属性和索引状态的扫描效率。</p>
            </div>
          </div>

          <div class="detail-actions">
            <button class="preview-btn" @click="previewOpen = true">
              <Eye class="h-4 w-4" />
              <span>打开预览</span>
            </button>
            <button>
              <RefreshCw class="h-4 w-4" />
              <span>重新解析</span>
            </button>
          </div>
        </aside>

        <div v-if="previewOpen" class="modal-backdrop" @click.self="previewOpen = false">
          <div class="preview-modal">
            <header class="preview-head">
              <div>
                <p>文档预览</p>
                <h2>{{ selectedDocument.name }}</h2>
              </div>
              <button class="icon-btn" aria-label="close preview" @click="previewOpen = false">
                <X class="h-5 w-5" />
              </button>
            </header>

            <div class="preview-body">
              <aside class="toc-pane">
                <div class="toc-title">
                  <BookOpen class="h-4 w-4" />
                  <span>目录结构</span>
                </div>
                <div class="toc-tree">
                  <details v-for="item in toc" :key="item.id" open>
                    <summary>
                      <ChevronDown class="h-3.5 w-3.5" />
                      <span>{{ item.title }}</span>
                      <em>P{{ item.page }}</em>
                      <b>{{ item.summary }}</b>
                    </summary>
                    <button v-for="child in item.children" :key="child.id">
                      <ChevronRight class="h-3.5 w-3.5" />
                      <span>{{ child.title }}</span>
                      <em>P{{ child.page }}</em>
                      <b>{{ child.summary }}</b>
                    </button>
                  </details>
                </div>
              </aside>

              <section class="original-pane">
                <div class="page-toolbar">
                  <span>原文视图</span>
                  <div>
                    <button>100%</button>
                    <button>单页</button>
                  </div>
                </div>
                <article class="paper">
                  <p class="paper-kicker">第 1 页 / 执行摘要</p>
                  <h3>2026 市场进入策略报告</h3>
                  <p>
                    当前市场窗口由企业内部知识沉淀、合规审计压力和大模型应用试点共同驱动。
                    文档建议优先进入资料密度高、审批链条明确、问答场景可量化的客户群体。
                  </p>
                  <p>
                    第一阶段应以可控试点为主，交付目标包括知识库导入、目录构建、节点摘要生成、
                    引用定位和业务问答样例。第二阶段再扩展到多部门协同和权限治理。
                  </p>
                  <div class="paper-highlight">
                    右侧原文区域只展示文档内容；节点摘要保留在左侧目录 hover 浮层中，避免干扰阅读。
                  </div>
                  <p>
                    渠道层面建议形成行业样板、售前材料和交付清单，减少每次试点的重复解释成本。
                    风险控制重点是交付周期、数据质量、长文档解析稳定性和结果可追溯性。
                  </p>
                </article>
              </section>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.demo-page {
  --ink: #101828;
  --muted: #667085;
  --line: rgba(16, 24, 40, 0.1);
  --soft: #f3f6fb;
  --panel: rgba(255, 255, 255, 0.86);
  --blue: #2563eb;
  min-height: 100vh;
  height: 100vh;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  background: linear-gradient(135deg, #f8fafc 0%, #eef3f8 48%, #f8fafc 100%);
  color: var(--ink);
}

button {
  border: 0;
  font: inherit;
  cursor: pointer;
}

.app-rail {
  min-height: 0;
  padding: 20px 16px;
  border-right: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.68);
  backdrop-filter: blur(18px);
  display: flex;
  flex-direction: column;
  gap: 26px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: white;
  font-weight: 800;
  background: linear-gradient(135deg, #1f2937, #2563eb);
}

.brand strong,
.brand span {
  display: block;
}

.brand strong {
  font-size: 15px;
}

.brand span,
.rail-foot span {
  color: var(--muted);
  font-size: 12px;
}

.rail-nav {
  display: grid;
  gap: 6px;
}

.rail-nav button,
.folder-list button,
.settings-nav button {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  border-radius: 10px;
  color: #344054;
  background: transparent;
  text-align: left;
  transition: 160ms ease;
}

.rail-nav button {
  padding: 10px 12px;
}

.rail-nav button.active,
.rail-nav button:hover,
.folder-list button.active,
.folder-list button:hover,
.settings-nav button.active,
.settings-nav button:hover {
  color: var(--ink);
  background: rgba(37, 99, 235, 0.08);
}

.rail-foot {
  margin-top: auto;
  padding: 14px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.7);
}

.rail-foot p {
  font-size: 13px;
  font-weight: 700;
}

.workbench {
  height: 100vh;
  min-width: 0;
  min-height: 0;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.topbar,
.surface {
  border: 1px solid var(--line);
  background: var(--panel);
  box-shadow: 0 14px 34px rgba(16, 24, 40, 0.05);
  backdrop-filter: blur(16px);
}

.topbar {
  flex-shrink: 0;
  min-height: 68px;
  border-radius: 16px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.topbar-title {
  display: flex;
  align-items: center;
  gap: 18px;
  min-width: 0;
}

.topbar-title p,
.surface-head p {
  font-size: 11px;
  color: var(--muted);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.topbar-title h1 {
  font-size: 21px;
  font-weight: 750;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.icon-text,
.search-box,
.primary-btn,
.tool-btn,
.preview-btn,
.icon-btn,
.view-toggle,
.mode-strip button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.72);
  color: #344054;
  font-size: 13px;
}

.icon-text,
.search-box,
.primary-btn,
.tool-btn,
.preview-btn,
.mode-strip button {
  padding: 9px 12px;
}

.search-box {
  width: 260px;
  color: #98a2b3;
}

.primary-btn,
.preview-btn {
  color: #111827;
  border-color: rgba(17, 24, 39, 0.16);
  background: #ffffff;
  font-weight: 700;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
}

.primary-btn:hover,
.preview-btn:hover {
  background: #f8fafc;
  border-color: rgba(17, 24, 39, 0.24);
}

.documents-layout,
.settings-layout {
  flex: 1;
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 300px;
  gap: 12px;
  min-height: 0;
}

.settings-layout {
  grid-template-columns: 270px minmax(0, 1fr);
}

.surface {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border-radius: 16px;
}

.surface-head {
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid rgba(16, 24, 40, 0.06);
}

.surface-head h2 {
  margin-top: 2px;
  font-size: 15px;
  font-weight: 750;
}

.icon-btn {
  width: 36px;
  height: 36px;
  justify-content: center;
  padding: 0;
}

.folder-list,
.settings-nav {
  padding: 8px;
  display: grid;
  gap: 4px;
  overflow: auto;
}

.folder-list button {
  padding: 8px 9px;
}

.folder-list span {
  flex: 1;
  font-size: 13px;
}

.folder-list em {
  color: #98a2b3;
  font-size: 12px;
  font-style: normal;
}

.doc-pane,
.settings-main {
  display: flex;
  flex-direction: column;
}

.doc-head {
  align-items: flex-start;
}

.doc-tools {
  display: flex;
  gap: 8px;
}

.tool-btn.active {
  color: #1d4ed8;
  border-color: rgba(37, 99, 235, 0.24);
  background: rgba(37, 99, 235, 0.08);
}

.view-toggle {
  padding: 4px;
}

.view-toggle button {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--muted);
  background: transparent;
}

.view-toggle button.active {
  color: var(--ink);
  background: white;
  box-shadow: 0 6px 16px rgba(16, 24, 40, 0.08);
}

.mode-strip {
  flex-shrink: 0;
  margin: 6px 8px 0;
  padding: 5px 7px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(37, 99, 235, 0.16);
  color: #344054;
  font-size: 12px;
}

.mode-strip span {
  margin-right: auto;
  font-weight: 700;
}

.mode-strip button {
  padding: 5px 8px;
  color: #1d4ed8;
  background: white;
}

.list-insight {
  color: #64748b;
  background: rgba(248, 250, 252, 0.78);
  border-color: rgba(16, 24, 40, 0.08);
}

.list-insight em {
  color: #94a3b8;
  font-style: normal;
}

.doc-scroll {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.doc-scroll.scrollable {
  overflow-y: auto;
}

.doc-list {
  padding: 8px;
  display: grid;
  gap: 6px;
}

.doc-list-header {
  display: grid;
  grid-template-columns: minmax(260px, 1.05fr) minmax(230px, 1.15fr) 104px 88px 82px;
  gap: 12px;
  padding: 0 10px 4px;
  color: #98a2b3;
  font-size: 11px;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.doc-list > button,
.doc-grid > button {
  border: 1px solid transparent;
  border-radius: 13px;
  background: rgba(248, 250, 252, 0.86);
  text-align: left;
  transition: 160ms ease;
}

.doc-list > button {
  padding: 10px 12px;
  display: grid;
  grid-template-columns: minmax(260px, 1.05fr) minmax(230px, 1.15fr) 104px 88px 82px;
  align-items: center;
  gap: 12px;
}

.doc-list > button.active,
.doc-list > button:hover,
.doc-grid > button.active,
.doc-grid > button:hover {
  border-color: rgba(37, 99, 235, 0.18);
  background: white;
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.06);
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 3px;
  opacity: 0;
  transition: opacity 140ms ease;
}

.doc-list > button:hover .row-actions,
.doc-list > button.active .row-actions {
  opacity: 1;
}

.row-actions button {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  color: #64748b;
  background: transparent;
}

.row-actions button:hover {
  color: #111827;
  background: rgba(15, 23, 42, 0.06);
}

.doc-file-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.row-check {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  border-radius: 7px;
  color: #98a2b3;
  background: transparent;
}

.row-check.hidden {
  opacity: 0;
  pointer-events: none;
}

.row-check.checked {
  color: #2563eb;
  background: #eff6ff;
}

.doc-icon,
.detail-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  border: 1px solid transparent;
}

.doc-icon.pdf,
.detail-icon.pdf {
  color: #ef4444;
  background: #fef2f2;
  border-color: #fecaca;
}

.doc-icon.word,
.detail-icon.word {
  color: #3b82f6;
  background: #eff6ff;
  border-color: #bfdbfe;
}

.doc-icon.sheet,
.detail-icon.sheet {
  color: #22c55e;
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.doc-icon.slide,
.detail-icon.slide {
  color: #f97316;
  background: #fff7ed;
  border-color: #fed7aa;
}

.doc-icon.text,
.detail-icon.text {
  color: #6b7280;
  background: #f9fafb;
  border-color: #e5e7eb;
}

.doc-icon.default,
.detail-icon.default {
  color: #64748b;
  background: #f1f5f9;
  border-color: #e2e8f0;
}

.doc-file-cell > div {
  min-width: 0;
}

.doc-file-cell strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  line-height: 1.3;
}

.doc-file-cell span {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: 11px;
}

.doc-title-line,
.card-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-title-line strong {
  font-size: 14px;
}

.doc-summary-cell,
.doc-grid p,
.detail-section p,
.setting-note {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.doc-summary-cell {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.status {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 750;
}

.status.done {
  color: #067647;
  background: #dcfae6;
}

.status.running {
  color: #b54708;
  background: #fef0c7;
}

.doc-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  color: var(--muted);
  font-size: 12px;
}

.doc-meta em,
.doc-status-cell em {
  color: #98a2b3;
  font-size: 11px;
  font-style: normal;
}

.doc-status-cell {
  display: grid;
  gap: 4px;
  justify-items: start;
}

.doc-grid {
  padding: 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.pagination {
  flex-shrink: 0;
  padding: 7px 10px;
  border-top: 1px solid rgba(16, 24, 40, 0.07);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: rgba(255, 255, 255, 0.68);
}

.pagination > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}

.pagination strong {
  color: #344054;
}

.pagination span {
  color: var(--muted);
}

.page-controls {
  display: flex;
  align-items: center;
  gap: 5px;
}

.page-controls button {
  min-width: 32px;
  height: 30px;
  padding: 0 9px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: white;
  color: #344054;
  font-size: 12px;
}

.page-controls button.active {
  border-color: transparent;
  background: #2563eb;
  color: white;
}

.page-controls button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.doc-grid > button {
  padding: 14px;
}

.card-line {
  justify-content: space-between;
  margin-bottom: 12px;
}

.doc-grid strong {
  font-size: 14px;
}

.detail-pane {
  padding-bottom: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.detail-identity,
.detail-section,
.detail-actions {
  margin: 8px 10px;
}

.detail-identity {
  display: flex;
  flex-shrink: 0;
  gap: 12px;
  margin-top: 10px;
  margin-bottom: 6px;
}

.detail-identity h3 {
  font-size: 14px;
  font-weight: 750;
  line-height: 1.35;
}

.detail-identity span {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  font-size: 12px;
}

.detail-section,
.setting-card {
  border: 1px solid rgba(16, 24, 40, 0.08);
  border-radius: 13px;
  background: rgba(248, 250, 252, 0.78);
}

.detail-section {
  flex-shrink: 0;
  padding: 8px 9px;
}

.basic-detail {
  padding: 7px 9px;
}

.basic-detail .section-title {
  margin-bottom: 5px;
}

.basic-detail .property-list {
  gap: 4px 8px;
}

.basic-detail .property-list div {
  font-size: 11px;
}

.basic-detail .property-list span {
  font-size: 10px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  color: #344054;
}

.section-title h4 {
  font-size: 12px;
  font-weight: 750;
}

.property-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
}

.property-list div,
.kv-row {
  display: grid;
  gap: 2px;
  align-items: start;
  font-size: 12px;
}

.property-list span,
.quality-grid span,
.status-panel p {
  color: var(--muted);
}

.property-list strong {
  min-width: 0;
  color: #344054;
  font-weight: 650;
  word-break: break-word;
}

.status-panel {
  display: grid;
  gap: 4px;
  margin-bottom: 6px;
}

.status-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.status-panel em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: 11px;
  font-style: normal;
}

.progress-track {
  height: 5px;
  border-radius: 999px;
  overflow: hidden;
  background: #e8eef7;
}

.progress-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #3b82f6;
}

.quality-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 4px;
}

.quality-grid div {
  padding: 6px 5px;
  border-radius: 8px;
  background: white;
}

.quality-grid span,
.quality-grid strong {
  display: block;
}

.quality-grid span {
  font-size: 10px;
  white-space: nowrap;
}

.quality-grid strong {
  margin-top: 2px;
  font-size: 12px;
}

.quality-note {
  margin-top: 5px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 10px;
  padding: 6px 7px;
  font-size: 11px;
  line-height: 1.35;
}

.quality-note.ok {
  color: #067647;
  background: #ecfdf3;
}

.quality-note.warning {
  color: #b54708;
  background: #fffaeb;
}

.detail-actions {
  flex-shrink: 0;
  margin-top: auto;
  margin-bottom: 10px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.summary-detail {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.summary-scroll {
  flex: 1;
  min-height: 92px;
  max-height: none;
  overflow-y: auto;
  padding-right: 4px;
}

.preview-btn {
  justify-content: center;
}

.detail-actions button:not(.preview-btn) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 0;
  height: 34px;
  padding: 0 8px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: white;
  color: #344054;
  font-size: 13px;
  font-weight: 650;
}

.detail-actions .preview-btn {
  min-width: 0;
  height: 34px;
  padding: 0 8px;
  overflow: hidden;
}

.detail-actions span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 22px;
  background: rgba(15, 23, 42, 0.48);
  backdrop-filter: blur(6px);
}

.preview-modal {
  width: min(1180px, 100%);
  height: min(780px, 92vh);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.38);
  background: #f8fafc;
  box-shadow: 0 28px 80px rgba(15, 23, 42, 0.32);
}

.preview-head {
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: white;
}

.preview-head p {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.preview-head h2 {
  margin-top: 2px;
  font-size: 16px;
  font-weight: 750;
}

.preview-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 310px minmax(0, 1fr);
}

.toc-pane {
  border-right: 1px solid var(--line);
  background: #fff;
  overflow: auto;
}

.toc-title {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 14px 16px;
  display: flex;
  gap: 8px;
  align-items: center;
  background: white;
  border-bottom: 1px solid rgba(16, 24, 40, 0.06);
  font-size: 13px;
  font-weight: 750;
}

.toc-tree {
  padding: 10px;
}

.toc-tree details,
.toc-tree button {
  position: relative;
}

.toc-tree summary,
.toc-tree button {
  width: 100%;
  min-height: 34px;
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  border-radius: 9px;
  padding: 7px 8px;
  color: #344054;
  background: transparent;
  text-align: left;
  font-size: 13px;
  list-style: none;
}

.toc-tree summary::-webkit-details-marker {
  display: none;
}

.toc-tree button {
  margin-left: 15px;
  width: calc(100% - 15px);
  color: #475467;
}

.toc-tree summary:hover,
.toc-tree button:hover {
  color: var(--ink);
  background: rgba(37, 99, 235, 0.08);
}

.toc-tree span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toc-tree em {
  color: #98a2b3;
  font-size: 11px;
  font-style: normal;
}

.toc-tree b {
  position: absolute;
  left: calc(100% + 10px);
  top: 0;
  z-index: 4;
  width: 260px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(16, 24, 40, 0.1);
  background: #101828;
  box-shadow: 0 16px 42px rgba(16, 24, 40, 0.2);
  color: white;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
  white-space: normal;
  opacity: 0;
  transform: translateX(-4px);
  pointer-events: none;
  transition: 140ms ease;
}

.toc-tree summary:hover b,
.toc-tree button:hover b {
  opacity: 1;
  transform: translateX(0);
}

.original-pane {
  min-width: 0;
  overflow: auto;
  background: #eef2f7;
}

.page-toolbar {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.9);
  color: var(--muted);
  font-size: 13px;
}

.page-toolbar div {
  display: flex;
  gap: 6px;
}

.page-toolbar button {
  padding: 5px 9px;
  border-radius: 8px;
  background: #f2f4f7;
  color: #475467;
  font-size: 12px;
}

.paper {
  width: min(720px, calc(100% - 44px));
  min-height: 900px;
  margin: 22px auto 42px;
  padding: 54px 58px;
  background: white;
  box-shadow: 0 18px 42px rgba(16, 24, 40, 0.12);
}

.paper-kicker {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.paper h3 {
  margin: 12px 0 22px;
  font-size: 28px;
  font-weight: 780;
}

.paper p {
  margin-bottom: 18px;
  color: #344054;
  font-size: 15px;
  line-height: 1.9;
}

.paper-highlight {
  margin: 24px 0;
  padding: 16px;
  border-left: 4px solid var(--blue);
  background: #f5f7ff;
  color: #344054;
  font-size: 14px;
  line-height: 1.7;
}

.settings-nav button {
  padding: 12px;
}

.settings-nav span {
  display: grid;
  gap: 2px;
}

.settings-nav strong {
  font-size: 13px;
}

.settings-nav em {
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}

.save-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #067647;
  font-size: 13px;
  font-weight: 700;
}

.setting-content {
  padding: 14px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.setting-card {
  padding: 15px;
}

.setting-card.wide {
  grid-column: 1 / -1;
}

.card-head {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.card-head h3 {
  font-size: 14px;
  font-weight: 750;
}

.provider-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.provider {
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: white;
  text-align: left;
}

.provider.active {
  border-color: rgba(37, 99, 235, 0.24);
  background: #f5f7ff;
}

.provider strong,
.provider span,
.setting-card label span,
.setting-card label em {
  display: block;
}

.provider strong {
  font-size: 14px;
}

.provider span,
.setting-card label span {
  margin-top: 5px;
  color: var(--muted);
  font-size: 12px;
}

.setting-card label {
  display: block;
}

.setting-card label + label {
  margin-top: 10px;
}

.setting-card label em {
  margin-top: 5px;
  padding: 10px;
  border-radius: 10px;
  background: white;
  color: #344054;
  font-size: 12px;
  font-style: normal;
  word-break: break-word;
}

.kv {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  color: var(--muted);
  font-size: 13px;
}

.kv strong {
  color: var(--ink);
}

.task-table {
  display: grid;
}

.task-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1.8fr;
  gap: 12px;
  padding: 11px 0;
  border-bottom: 1px solid rgba(16, 24, 40, 0.07);
  align-items: center;
  font-size: 13px;
}

.task-row.head {
  padding-top: 0;
  color: var(--muted);
  font-size: 11px;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.task-row em {
  color: var(--muted);
  font-style: normal;
}

.profile-row {
  display: inline-flex;
  padding: 4px;
  border-radius: 12px;
  background: #eef2f7;
}

.profile-row button {
  min-width: 92px;
  padding: 8px 14px;
  border-radius: 9px;
  color: var(--muted);
  background: transparent;
}

.profile-row button.active {
  color: var(--ink);
  background: white;
  box-shadow: 0 6px 16px rgba(16, 24, 40, 0.08);
}

.security-list {
  display: grid;
  gap: 10px;
}

.security-list span {
  padding: 11px 12px;
  border-radius: 10px;
  background: white;
  color: #344054;
  font-size: 13px;
}

@media (max-width: 1280px) {
  .documents-layout {
    grid-template-columns: 230px minmax(0, 1fr);
  }

  .detail-pane {
    grid-column: 1 / -1;
  }
}

@media (max-width: 980px) {
  .demo-page,
  .documents-layout,
  .settings-layout,
  .preview-body,
  .provider-grid,
  .setting-content,
  .doc-grid {
    grid-template-columns: 1fr;
  }

  .app-rail {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .topbar,
  .topbar-title,
  .topbar-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .search-box {
    width: 100%;
  }

  .toc-tree b {
    left: 8px;
    top: 100%;
  }
}

@media (max-width: 680px) {
  .workbench {
    padding: 12px;
  }

  .doc-list > button,
  .task-row {
    grid-template-columns: 1fr;
  }

  .doc-list > button {
    flex-direction: column;
    align-items: flex-start;
  }

  .doc-meta,
  .mode-strip {
    flex-wrap: wrap;
  }

  .paper {
    width: calc(100% - 20px);
    padding: 28px 22px;
  }
}
</style>
