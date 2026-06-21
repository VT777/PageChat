# AI Knowledge Current E2E Baseline 2026-06-21

这份文件记录当前 `task6-full-final-v3` 的端到端结果快照。它只作为问题定位和后续回归对照，不代表当前 TOC 已满足最终预期。

当前结果来源：

- E2E 目录：`D:\projects\page_chat\eval0618\task6-full-final-v3`
- 汇总文件：`D:\projects\page_chat\eval0618\task6-full-final-v3\summary.json`
- 参考文件：`D:\projects\page_chat\docs\architecture\ai_knowledge_expected_toc_reference.md`

## 结论

- 13 份文件均返回 `status=ok`，但这只说明流程没有崩溃。
- 13 份文件的 `quality.status` 均为 `needs_review`。
- 当前 E2E 验收还不够强，不能证明 TOC 页码、目录层级、图目录/表目录隔离和长章节子树质量都符合预期。
- 后续重构必须用 `ai_knowledge_expected_toc_reference.md` 中的真实节点和物理页码作为硬参考。

## 当前结果表

| ID | 文件 | 耗时秒 | 类型 | 路径 | 状态 | 质量 | 节点数 | 根节点 | sections |
|---|---|---:|---|---|---|---|---:|---:|---|
| T01 | 2025全球人工智能技术应用洞察报告.pdf | 113.677 | ocr | embedded_toc | ok | needs_review | 40 | 6 |  |
| T02 | 2025年AI治理报告：回归现实主义.pdf | 126.818 | ocr | embedded_toc | ok | needs_review | 12 | 7 |  |
| T03 | 2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf | 107.749 | ocr | visible_toc_with_pages | ok | needs_review | 48 | 1 | main_toc |
| T04 | 2025年第五范式-人工智能驱动的科技创新报告.pdf | 14.077 | text | visible_toc_no_pages | ok | needs_review | 45 | 6 |  |
| T05 | 2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf | 4.556 | text | visible_toc_no_pages | ok | needs_review | 17 | 1 | main_toc |
| T06 | 2026年AI Agent智能体技术发展报告.pdf | 7.432 | text | embedded_toc | ok | needs_review | 118 | 9 |  |
| T07 | 2026年快消行业AI营销增长白皮书.pdf | 32.606 | hybrid | visible_toc_no_pages | ok | needs_review | 15 | 1 | main_toc |
| T08 | AI眼镜关键技术与产业生态研究报告（2025年）.pdf | 4.177 | text | visible_toc_with_pages | ok | needs_review | 33 | 3 | main_toc, figure_toc, table_toc |
| T09 | OpenAI深度报告：大模型王者，引领AGI之路.pdf | 26.272 | text | visible_toc_with_pages | ok | needs_review | 62 | 3 | main_toc, figure_toc, table_toc |
| T10 | 中国AI+营销趋势洞察2026.pdf | 1.884 | text | embedded_toc | ok | needs_review | 15 | 15 |  |
| T11 | 人工智能安全治理研究报告（2025年）.pdf | 6.525 | text | visible_toc_with_pages | ok | needs_review | 32 | 2 | main_toc, figure_toc |
| T12 | 清华大学：职业教育人工智能应用发展报告（2024-2025）.pdf | 13.159 | text | visible_toc_no_pages | ok | needs_review | 42 | 1 | main_toc |
| T13 | 生成式人工智能服务合规备案指南（2026年）.pdf | 5.426 | text | embedded_toc | ok | needs_review | 65 | 3 | main_toc, figure_toc, table_toc |

## 已知风险

这些风险来自人工审查和当前参考文件，不一定都在 `task6-full-final-v3` 的弱 E2E 检查中被标为失败。

- T03 重庆案例：需要拒绝大量节点塌缩到同一页；目录应完整映射到物理页 3-43。
- T04 第五范式：不能只停在一级目录；顶层范围应为 3-12、13-34、35-48、49-60、61-68。
- T05 2026AI 应用专题：章节分隔页应作为章节起始页，不应映射成 `divider + 1`。
- T07 快消白皮书：顶层范围基本明确，但长章节必须继续生成子树。
- T08 AI 眼镜：主目录、图目录、表目录必须独立；主目录不能丢失括号子项。
- T09 OpenAI 深度报告：目录页给出的页码本身是物理页，不应被 weak outline marker 或错误 offset 覆盖。
- T11 人工智能安全治理：主目录括号子项和图目录都必须保留。
- T12 清华职教：顶层范围基本正确，但长叶子如 `8.6 [167-201]` 不能被视为完全通过。
- T13 合规备案：主目录、图目录、表目录需要独立；第五章不能混入表格单元格、日期、机构名等噪声。

## 后续验收要求

后续每个 phase 完成后都必须：

1. 运行单元测试覆盖当期改动。
2. 逐个运行 13 份真实 PDF 的诊断或 E2E。
3. 对照 `ai_knowledge_expected_toc_reference.md` 检查关键节点和物理页码。
4. 记录耗时、路径、TOC source、mapping report、child expansion report、quality report。
5. 通过后再提交。
