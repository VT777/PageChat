# PageIndex TOC 准确率与速度改进计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 减少 balanced 模式 LLM 调用次数约 70%（从 ~44 次降到 ~13 次），同时提升 TOC 检测准确率和管道可靠性。

**Architecture:** 六项独立改进，按"高收益低风险"排序。核心思路是利用 Qwen3.5-flash 1M context window 的巨大余量，通过增大批次/分组来减少调用次数；同时修复无限循环风险和同步阻塞问题。每个 Task 独立可测、独立可提交。

**Tech Stack:** Python 3.14, FastAPI, asyncio, OpenAI-compatible API (DashScope/Qwen3.5-flash)

---

## 文件结构

| 文件 | 职责 | 改动类型 |
|------|------|----------|
| `backend/pageindex/page_index.py` | 核心索引管道 | 修改 |
| `backend/app/core/config.py` | 配置参数 | 修改 |
| `backend/app/prompts/pageindex_prompts.py` | 提示词模板 | 修改（新增批量验证 prompt） |
| `backend/tests/test_toc_pipeline_optimizations.py` | 新增测试 | 创建 |

---

### Task 1: 增大 TOC 检测批次 + 提升截断限制 + 扫描范围

**Files:**
- Modify: `backend/pageindex/page_index.py:118` (`toc_detector_batch` batch_size 5→15)
- Modify: `backend/pageindex/page_index.py:144` (content[:500]→[:1000])
- Modify: `backend/app/core/config.py:125` (`toc_check_page_num` 8→15)
- Test: `backend/tests/test_toc_pipeline_optimizations.py`

**当前问题:**
- `batch_size=5`，每页截断 500 字符 → 检测 15 页需 3 次 LLM 调用
- `toc_check_page_num=8`，官方是 20，长前言文档会漏检 TOC
- 500 字符截断可能丢失 TOC 特征（如页码出现在 500 字符之后）

**改进:**
- `batch_size` 5 → **15**（15 页 × 1000 字符 ≈ 5000 tokens，远在 1M 限制内）
- 每页截断 500 → **1000** 字符
- `toc_check_page_num` 8 → **15**

**效果:** TOC 检测从 ~3-4 次 LLM 调用降到 **1 次**，准确率提升。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_toc_pipeline_optimizations.py
import json
from unittest.mock import patch
from backend.pageindex.page_index import toc_detector_batch

def test_toc_detector_batch_uses_larger_batch_and_longer_content():
    """batch_size default=15, content truncated at 1000 chars."""
    pages = [(i, "x" * 1200) for i in range(20)]
    captured = {}
    def mock_api(model, prompt, **kw):
        captured["prompt"] = prompt
        return json.dumps({"toc_pages": [], "reasoning": "none"})
    with patch("backend.pageindex.page_index.ChatGPT_API", mock_api):
        toc_detector_batch(pages, model="test")  # use default batch_size
    assert "[Page 14]" in captured["prompt"]       # 15th page in batch
    assert "x" * 1000 in captured["prompt"]        # 1000 char truncation
    assert "x" * 1001 not in captured["prompt"]    # not more
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest backend/tests/test_toc_pipeline_optimizations.py -v`
Expected: FAIL (current batch_size=5, truncation=500)

- [ ] **Step 3: 修改代码**

`page_index.py:118`: `batch_size=5` → `batch_size=15`
`page_index.py:144`: `content[:500]` → `content[:1000]`
`config.py:125`: `"toc_check_page_num": 8` → `"toc_check_page_num": 15`

- [ ] **Step 4: 运行测试确认通过 + 全量回归**

Run: `pytest backend/tests/ -v`

- [ ] **Step 5: Commit**

```bash
git commit -m "perf: increase TOC detection batch(15 pages), truncation(1000 chars), scan range(15 pages)"
```

---

### Task 2: 增大 page_list_to_group_text 分组上限

**Files:**
- Modify: `backend/pageindex/page_index.py:540` (`max_tokens=20000` → `60000`)
- Test: `backend/tests/test_toc_pipeline_optimizations.py`

**当前问题:** 默认 `max_tokens=20000`，Qwen3.5-flash 支持 1M context，仅用 2%。30 页 PDF 可能拆成 2 组，多一次 `generate_toc_continue` 且积累误差。

**改进:** `max_tokens` 默认值 20000 → **60000**。

**效果:**
- 30 页 PDF（~20K tokens）保证 1 组，省 1 次调用
- 100 页 PDF（~80K tokens）从 4 组降到 2 组，省 2 次调用
- 减少 `generate_toc_continue` 的上下文累积误差

- [ ] **Step 1: 写失败测试**

```python
from backend.pageindex.page_index import page_list_to_group_text

def test_page_list_to_group_text_default_max_tokens_is_60000():
    """40000 total tokens should fit in 1 group with new 60K limit."""
    page_contents = [f"page {i} " * 50 for i in range(40)]
    token_lengths = [1000] * 40  # 40000 total
    groups = page_list_to_group_text(page_contents, token_lengths)
    assert len(groups) == 1
```

- [ ] **Step 2: 运行测试确认失败** (当前 20K 会产生 2+ 组)

- [ ] **Step 3: 修改** `page_index.py:540`: `max_tokens=20000` → `max_tokens=60000`

- [ ] **Step 4: 运行测试确认通过 + 全量回归**

- [ ] **Step 5: Commit**

```bash
git commit -m "perf: increase page group token limit from 20K to 60K, fewer LLM calls for large docs"
```

---

### Task 3: 批量化 verify_toc 和 check_title_appearance_in_start

**Files:**
- Modify: `backend/app/prompts/pageindex_prompts.py` — 新增 `CHECK_TITLE_APPEARANCE_BATCH_PROMPT` 和 `CHECK_TITLE_START_BATCH_PROMPT`
- Modify: `backend/pageindex/page_index.py` — 新增 `check_title_appearance_batch()` 和 `check_title_start_batch()` 函数；修改 `verify_toc` (line ~1483) 和 `check_title_appearance_in_start_concurrent` (line ~85)
- Test: `backend/tests/test_toc_pipeline_optimizations.py`

**当前问题:** 15 条目 → verify 15 次 + start_check 15 次 = **30 次 LLM 调用**，是单次解析中最大的调用源。

**改进思路:**
1. 新增批量 prompt，每次传入最多 10 个 `(title, page_text)` 对
2. 新增 `check_title_appearance_batch(items, model, batch_size=10)` async 函数
3. 新增 `check_title_start_batch(items, model, batch_size=10)` async 函数
4. 解析失败时降级为逐项调用（兼容性兜底）
5. `verify_toc` 和 `check_title_appearance_in_start_concurrent` 改为调用 batch 版本

**Batch prompt 设计:**

```python
CHECK_TITLE_APPEARANCE_BATCH_PROMPT = """For each item, judge whether the section title appears on the given page.
Rules: fuzzy matching for spacing/punctuation; ignore image markdown and decorations; "yes" only if title is clearly present.

Items:
{items_json}

Reply JSON array only (no markdown fence):
[{{"id": 1, "answer": "yes or no"}}, ...]"""

CHECK_TITLE_START_BATCH_PROMPT = """For each item, decide whether the section starts at the beginning of its page.
Rules: ignore non-content prefixes; fuzzy matching; "yes" only if first meaningful heading matches the title.

Items:
{items_json}

Reply JSON array only (no markdown fence):
[{{"id": 1, "start_begin": "yes or no"}}, ...]"""
```

**效果:** 30 次调用 → **~4 次调用** (verify 2 + start_check 2)

- [ ] **Step 1: 添加 batch prompt 到 pageindex_prompts.py**

- [ ] **Step 2: 实现 `check_title_appearance_batch` 和 `check_title_start_batch`**

关键设计：
- 每批最多 10 个 `(id, title, page_text[:2000])` 对
- page_text 截断到 2000 字符避免超大 prompt
- 用 `asyncio.gather` 并发执行多个批次
- JSON 解析失败时 fallback 到逐项调用

```python
async def check_title_appearance_batch(items, model, batch_size=10):
    """Batch-check multiple (title, page_text) pairs in fewer LLM calls."""
    all_results = {}
    batches = [items[i:i+batch_size] for i in range(0, len(items), batch_size)]

    async def _run_batch(batch):
        items_json = json.dumps([
            {"id": it["id"], "title": it["title"], "page_text": it["page_text"][:2000]}
            for it in batch
        ], ensure_ascii=False)
        prompt = CHECK_TITLE_APPEARANCE_BATCH_PROMPT.format(items_json=items_json)
        try:
            resp = await ChatGPT_API_async(model=model, prompt=prompt)
            parsed = extract_json(resp)
            if isinstance(parsed, list):
                return {r["id"]: r.get("answer", "no") for r in parsed}
            raise ValueError("not a list")
        except Exception:
            # Fallback: per-item
            results = {}
            for it in batch:
                r = await check_title_appearance(it, ...)
                results[it["id"]] = r["answer"]
            return results

    batch_results = await asyncio.gather(*[_run_batch(b) for b in batches])
    for br in batch_results:
        all_results.update(br)
    return all_results
```

- [ ] **Step 3: 修改 `verify_toc` (line ~1483-1487)** — 替换 per-item gather 为 batch 调用

- [ ] **Step 4: 修改 `check_title_appearance_in_start_concurrent` (line ~85-97)** — 同理

- [ ] **Step 5: 写测试验证批量调用减少了 LLM 调用次数**

```python
@pytest.mark.asyncio
async def test_verify_toc_uses_batch_calls():
    """15 items should need ~2 batch calls, not 15 individual calls."""
    call_count = {"n": 0}
    async def counting_mock(model, prompt, **kw):
        call_count["n"] += 1
        return json.dumps([{"id": i, "answer": "yes"} for i in range(10)])
    # ... mock and run verify_toc with 15 items
    assert call_count["n"] <= 4  # ~2 for verify batch, not 15
```

- [ ] **Step 6: 运行全量测试**

- [ ] **Step 7: Commit**

```bash
git commit -m "perf: batch verify_toc and check_title_start, ~30 LLM calls reduced to ~4"
```

---

### Task 4: toc_transformer 加 max_attempts 上限

**Files:**
- Modify: `backend/pageindex/page_index.py:363` (while-loop 加计数器)
- Test: `backend/tests/test_toc_pipeline_optimizations.py`

**当前问题:** `while not (if_complete == "yes" and finish_reason == "finished")` **无上限**，可能永远循环挂死进程。

**改进:** 加 `max_continuation_attempts=5` 计数器，超过后 break 并使用已有结果。

- [ ] **Step 1: 写测试**

```python
def test_toc_transformer_stops_after_max_continuation_attempts():
    """Should terminate after 5 continuation rounds even if never 'complete'."""
    call_count = {"n": 0}
    def mock_never_finish(model, prompt, **kw):
        call_count["n"] += 1
        return '{"table_of_contents": []}', "max_output_reached"
    def mock_never_complete(toc, resp, model):
        return "no"
    with patch(...):
        result = toc_transformer("some toc", "test-model")
    # 1 init + 1 check + 5*(1 continue + 1 check) = 12
    assert call_count["n"] <= 12
```

- [ ] **Step 2: 修改 page_index.py:363**

在 while-loop 前加:
```python
max_continuation_attempts = 5
continuation_count = 0
```
条件改为: `while not (...) and continuation_count < max_continuation_attempts:`
循环体内加: `continuation_count += 1`

- [ ] **Step 3: 运行测试**

- [ ] **Step 4: Commit**

```bash
git commit -m "fix: cap toc_transformer continuation loop at 5 attempts, prevent infinite hang"
```

---

### Task 5: single_toc_item_index_fixer 改为异步

**Files:**
- Modify: `backend/pageindex/page_index.py:1261` (def→async def)
- Modify: `backend/pageindex/page_index.py:1281` (ChatGPT_API→await ChatGPT_API_async)
- Modify: `backend/pageindex/page_index.py:1359` (调用方加 await)
- Test: `backend/tests/test_toc_pipeline_optimizations.py`

**当前问题:** 同步 `ChatGPT_API()` 在 `asyncio.gather` 里阻塞 event loop。3 个错误条目的修复实际串行执行（~6s），而非并行（~2s）。

- [ ] **Step 1: 写测试**

```python
@pytest.mark.asyncio
async def test_single_toc_item_index_fixer_is_async():
    """Fixer must be a coroutine function for true parallel execution."""
    import inspect
    from backend.pageindex.page_index import single_toc_item_index_fixer
    assert inspect.iscoroutinefunction(single_toc_item_index_fixer)
```

- [ ] **Step 2: 修改函数**

Line 1261: `def` → `async def`
Line 1281: `ChatGPT_API(...)` → `await ChatGPT_API_async(...)`
Line 1359: `single_toc_item_index_fixer(...)` → `await single_toc_item_index_fixer(...)`

- [ ] **Step 3: 运行全量测试**

- [ ] **Step 4: Commit**

```bash
git commit -m "perf: make single_toc_item_index_fixer async for true parallel fixing"
```

---

### Task 6: verify_toc 大文档自动采样

**Files:**
- Modify: `backend/pageindex/page_index.py:1463-1470` (`verify_toc` N=None 逻辑)
- Test: `backend/tests/test_toc_pipeline_optimizations.py`

**当前问题:** 全量验证所有条目。50+ 条目的大文档开销很大（即使批量化后也需 5+ 批次）。

**改进:** 当条目数 > 25 时，自动采样 `max(20, int(N * 0.7))`。小文档（≤25）仍全量验证。

- [ ] **Step 1: 写测试**

```python
def test_verify_toc_samples_for_large_item_counts():
    """30 items -> should sample max(20, 30*0.7)=21, not all 30."""
    # ... mock 30 valid items, verify that only ~21 are checked

def test_verify_toc_checks_all_for_small_item_counts():
    """15 items -> should check all 15."""
    # ... mock 15 items, verify all 15 are checked
```

- [ ] **Step 2: 修改 verify_toc line 1463-1470**

```python
if N is None:
    total = len(list_result)
    if total > 25:
        N = max(20, int(total * 0.7))
        print(f"auto-sampling {N} of {total} items for verification")
        sample_indices = random.sample(range(0, total), N)
    else:
        print("check all items")
        sample_indices = range(0, total)
```

- [ ] **Step 3: 运行测试**

- [ ] **Step 4: Commit**

```bash
git commit -m "perf: auto-sample verify_toc for documents with >25 TOC entries"
```

---

## 预期效果汇总

### LLM 调用次数（30 页 PDF with TOC, 15 条目, happy path）

| 步骤 | 改进前 | 改进后 | 节省 |
|------|--------|--------|------|
| TOC 检测 (find_toc_pages) | 4 | **1** | 3 |
| 页码检测 (detect_page_index) | 1 | 1 | 0 |
| TOC 转换 (toc_transformer) | 2 | 2 | 0 |
| 索引提取 (toc_index_extractor) | 1 | 1 | 0 |
| TOC 验证 (verify_toc) | 15 | **2** | 13 |
| 标题位置检查 (check_start) | 15 | **2** | 13 |
| 大节点递归 | ~6 | ~4 | 2 |
| **总计** | **~44** | **~13** | **~31 (-70%)** |

### 可靠性

- toc_transformer 无限循环 → max_attempts=5 兜底
- single_toc_item_index_fixer 阻塞 event loop → async 真正并行

### 准确率

- toc_check_page_num 8→15: 长前言文档不再漏检 TOC
- 每页截断 500→1000 字符: TOC 特征检测更可靠
- 分组上限 20K→60K: 减少分组拆分，减少 generate_toc_continue 累积误差
