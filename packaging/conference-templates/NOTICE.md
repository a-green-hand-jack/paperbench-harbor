# Conference templates

The directories `cvpr2025/` and `iclr2025/` are the official LaTeX author
templates used by PaperOrchestra/PaperWritingBench. They were copied
unmodified from the paper-orchestra repository
(`google-research/paper-orchestra`, revision
`ca1b3fa01c2970fc7cda32d16245db38d57b3f56`, Apache-2.0) which in turn
distributes the conference author kits.

- `cvpr2025/` — CVPR 2025 author kit (cvpr.sty, preamble.tex, template.tex,
  guidelines.md, bibliography style, template bibliography).
- `iclr2025/` — ICLR 2025 author kit (iclr2025_conference.sty,
  math_commands.tex, template.tex, guidelines.md, bibliography style,
  template bibliography).

They are bundled here so Harbor task environments can compile papers without
network access. The templates remain the property of their respective
conferences and are redistributed only for paper formatting. The benchmark
papers themselves are downloaded on demand from the upstream Hugging Face
dataset `yiwen-song/PaperWritingBench` (Apache-2.0 for the dataset packaging)
and are never committed to this repository.
