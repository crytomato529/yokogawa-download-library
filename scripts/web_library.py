"""Use the proven file downloader with a brand-specific state and source URL."""

from pathlib import Path

import schneider_download_library as engine


class WebLibrary:
    def __init__(self, brand: str):
        self.brand = brand

    def main(self, argv: list[str]) -> int:
        args = engine.build_parser().parse_args(argv)
        if args.command != "download":
            raise ValueError("Web-only brands use imported search results, not a native library API")
        if not args.state:
            args.state = str(Path(args.dir) / f".{self.brand}_download_state.json")
        return engine.command_download(args)
