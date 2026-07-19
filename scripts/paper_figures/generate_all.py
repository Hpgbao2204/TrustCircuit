"""CLI orchestration for the six redesigned paper figures."""

from __future__ import annotations

from . import generate_fig1, generate_fig2, generate_fig3, generate_fig4, generate_fig5, generate_fig6


def main() -> None:
    generated = []
    for module in (generate_fig1, generate_fig2, generate_fig3, generate_fig4, generate_fig5, generate_fig6):
        generated.extend(module.generate())
    if len(generated) != 28 or len(set(generated)) != 28:
        raise RuntimeError(f"Expected 28 unique panels, got {len(generated)}")
    print(f"generated {len(generated)} independent vector PDFs")


if __name__ == "__main__":
    main()
