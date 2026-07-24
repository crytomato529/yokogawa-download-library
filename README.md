# Yokogawa Download Library

语言 / Language: **中文** | [English](README.en.md)

一个通用的横河电机资料库同步工具。它可以按关键词或分类搜索横河公开资料库，导出完整清单，对比新旧清单，并增量归档可访问资料。工具本体是独立 Python 命令行脚本，不依赖 Codex，也不依赖浏览器点击；Claude Code、Cursor、其他 AI Agent、自动化脚本或人工命令行都可以直接使用。

仓库中的 `SKILL.md` 只是给 Codex 使用的可选适配说明；核心能力在 `scripts/yokogawa_library.py`。

## 适合用途

- 搜索并归档横河产品资料，例如 `prosafe-rs`
- 导出 JSON/CSV 清单
- 对比两次搜索结果，发现新增、删除或变更
- 下载公开 PDF、ZIP、软件包等直链文件
- 将公开详情页保存为 HTML 归档
- 中断后重新运行并自动跳过已完成项目

## 常用命令

搜索并生成清单：

```bash
python scripts/yokogawa_library.py search --keyword "prosafe-rs" --out prosafe-rs_manifest.json --csv prosafe-rs_manifest.csv
```

全量同步。首次正式运行请不要加 `--limit`：

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest prosafe-rs_manifest.json --csv prosafe-rs_manifest.csv --dir prosafe-rs_downloads
```

中断后继续：

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest prosafe-rs_manifest.json --csv prosafe-rs_manifest.csv --dir prosafe-rs_downloads
```

烟测或限速归档：

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest prosafe-rs_manifest.json --csv prosafe-rs_manifest.csv --dir prosafe-rs_downloads --limit 2
```

只下载原始文件直链，不保存详情页 HTML：

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest prosafe-rs_manifest.json --dir prosafe-rs_downloads --direct-only
```

## 文件命名

下载文件和页面归档按以下规则保存：

```text
<文档类型> - <文档号> - <文档名称> - <版本>.<扩展名>
```

示例：

```text
Technical Information - TI 32S01J30-01E - Explosion Protection (ProSafe-RS) - Edition 26.pdf
```

## 注意事项

- `--limit` 仅用于测试、临时限速或验证断点续传，不适合正式首次全量归档。
- 下载状态保存在下载目录的 `.yokogawa_download_state.json` 中。
- 脚本会跳过登录、锁定或软件协议确认类条目，除非后续另行实现授权流程。
