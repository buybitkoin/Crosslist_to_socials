import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cli.commands import cli

if __name__ == "__main__":
    cli()
