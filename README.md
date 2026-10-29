# Yokogawa 产品手册采集工具

语言 / Language: **中文** | [English](README.en.md)

面向 ProSafe-RS 等产品的通用资料采集工具：官方检索、公开网页补搜、累积清单、版本比对和可恢复下载。可用于 Codex、Claude Code、Cursor、其他 AI 工具或独立 Python 脚本，无须模拟浏览器点击。

**先全量收集可访问候选，后续更新清单或中断续传；“可下载”不等于“最新适用”。** 本工具输出可追溯的本地 RAG 文件索引，不部署向量数据库，也不替代工程审核。

## 2026-10-30 更新

- 新增 `resume`：按已有清单续传，不重搜、不消耗搜索服务额度、不刷新旧观察日期。
- 官方入口解析：配置 `seed_pages`，限额读取公开 HTML 及一层文档页；识别已知无后缀 PDF 地址，报告未访问与失败页面。
- 文档号查缺：从实际 PDF 提取编号、页码和证据，精确比对清单；精选编号加入 `document_numbers` 补搜。
- RAG 版本隔离：保留历史文件，另导出当前本地索引；不把新版本元数据套到旧文件上。
- 完整性与效率：哈希校验、链接去重、受限接口停止别名重复请求、同链接内容复查、多产品故障隔离。

## 快速开始

Python 3.10+。下载与清单管理使用标准库；PDF 引用提取可选安装 `pypdf` 或 PyMuPDF，证书信任库不完整时可选 `certifi`。

```bash
git clone https://github.com/crytomato529/yokogawa-download-library.git
cd yokogawa-download-library
python scripts/manual_watch.py plan --config references/manual-watch.example.json --out web-query-plan.json
```

让 AI 工具执行搜索计划，并按 [结果格式](references/manual-watch.md) 导出本次真实的 `web-results.json`，随后运行：

```bash
python scripts/manual_watch.py run --config references/manual-watch.example.json --root manual-library --web-results web-results.json
```

默认下载全部可访问的 PDF 候选。正式运行不要加 `--limit` 或 `--max-results`；这两个参数只用于小批测试，不是限速选项。官网其他资料仍保留在清单中，更多下载格式可配置 `download_formats`。使用同一个固定输出目录，不要把既有资料移入 skill 安装目录。

纯脚本补搜可选 `--web-provider tavily` 代替 `--web-results`，并在进程环境设置 `TAVILY_API_KEY`；可能消耗搜索服务额度。通过其他搜索工具导入无需另配密钥。独立 Tavily HTTP 后端本轮未使用专用密钥实测。密钥不要写入配置或仓库。

## 更新与续传

仅继续已有下载，不重搜：

```bash
python scripts/manual_watch.py resume --config references/manual-watch.example.json --root manual-library
```

检查已归档链接是否被静默替换：

```bash
python scripts/manual_watch.py resume --config references/manual-watch.example.json --root manual-library --revalidate
```

要查新资料时，重新执行 `plan`、获取新搜索结果并执行 `run`。单个文件中断后会重新下载该文件，不是字节级续传；完成且哈希一致的文件跳过。新版本与旧文件并存，暂未再搜到的记录不自动删除。超过 24 小时的导入搜索结果默认标记过期。

单品牌官方入口仍保留：

```bash
python scripts/yokogawa_library.py search --keyword "prosafe-rs" --out manifest.json --csv manifest.csv
python scripts/yokogawa_library.py download --manifest manifest.json --dir downloads
```

横河公开 Library API 支持按关键词逐页枚举。本轮 `prosafe-rs` 得到 265 条、134 个直链，这只是当次检索范围，不是永久总数。详情页可能被 WAF 拦截；默认只下载直链，保留 `--direct-only` 兼容选项。仅显式加 `--include-detail-pages` 才尝试保存公开 HTML，网页不是已下载手册。

## 目录查缺

编辑 [配置示例](references/manual-watch.example.json) 中的关键词、别名、`document_numbers` 和可选 `seed_pages`。按需预览官方链接或检查本地文档引用：

```bash
python scripts/manual_watch.py discover --config references/manual-watch.example.json --out public-links.json
python scripts/manual_references.py --brand yokogawa --pdf manual.pdf --catalog manifest.json --out reference-gaps.json
```

PDF 默认只检查前 40 页、最多 100 个编号，`--max-pages 0` 可扫描全文；不执行 OCR。结果可能包含本册编号、其他产品、不同语言和旧版资料，不要把全部线索自动视为缺失手册并发起上百次搜索。详细规则和官方来源见 [深度采集](references/deep-collection.md)。

## 文件与索引

命名：`文档类型 - 文档号 - 文档名称 - 版本.扩展名`。未知字段省略；同名冲突保留独立文件。空内容、HTML 登录/拦截页和格式签名错误不能成为已完成下载。

| 输出 | 用途 |
| --- | --- |
| `catalog.json` / `catalog.csv` | 累积资料清单，含观察时间和来源 |
| `download-manifest.json` / `downloads/` | 下载候选、文件、原子状态及错误 |
| `runs/` / `latest-report.json` | 历次发现证据、覆盖与失败报告 |
| `latest-resume-report.json` | 不重搜续传的独立记录 |
| `rag-index.jsonl` | 已验证文件的当前与历史索引、来源和哈希 |
| `rag-current.jsonl` | 去重后的当前本地记录，排除已知新版待下载的旧文件 |

当前本地索引不等于最新版目录，尤其不能跨不同 URL、语言和软硬件发布版自动确定适用性。建库前区分手册、规格书、培训和市场资料；方案审核仍须核对版本、适用范围和原文页码。

## 验证与边界

```bash
python -B -m unittest discover -s scripts -p "test_*.py"
```

本次 GitHub 发布前两套项目各 54 项测试通过，含保留旧版命令行为的 4 项兼容测试；真实下载证据和未解决限制见 [验收记录](VALIDATION.md)。官方全量枚举仅指给定查询范围；搜索引擎不能证明全网完整。安装或更新不创建定时任务，也不接受软件协议或绕过登录。

AI 使用入口：[SKILL.md](SKILL.md)，技能名 `yokogawa-library`。`agents/` 中的 Codex 界面元数据是可选的，核心脚本和说明不依赖特定 AI 工具。调度请使用宿主工具，在确定产品、频率和输出目录后配置；不需要为已确定的下载/状态操作反复调用模型。
