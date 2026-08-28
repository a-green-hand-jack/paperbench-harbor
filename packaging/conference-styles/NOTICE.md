# Conference style files

Style files in this directory are copied into task environments so papers can
be compiled without network access. They are third-party files distributed by
their conferences and are bundled solely for paper formatting.

- `neurips_2025.sty` — NeurIPS 2025 LaTeX style, obtained from the official
  distribution at <https://media.neurips.cc/Conferences/NeurIPS2025/Styles.zip>.
  Copyright belongs to the NeurIPS Foundation. Bundled unmodified.
- `iclr2026_conference.sty` / `iclr2026_conference.bst` — ICLR 2026 LaTeX
  style and bibliography style, obtained from the official ICLR GitHub
  distribution at <https://github.com/ICLR/Master-Template/blob/master/iclr2026.zip>.
  Copyright belongs to the ICLR organizers. Bundled unmodified; no explicit
  license is stated in the official distribution.
- `icml2025.sty` — official ICML 2025 LaTeX style, obtained from the ICML
  2025 author kit at
  <https://media.icml.cc/Conferences/ICML2025/Styles/icml2025.zip>. It carries
  no explicit license statement and is distributed by ICML for preparing ICML
  2025 submissions.
- `acl.sty`, `acl_natbib.bst` — ACL/NAACL LaTeX style, obtained unmodified
  from the official repository at <https://github.com/acl-org/acl-style-files>.
  Distributed under the LaTeX Project Public License (LPPL).
- `iccv.sty` — ICCV 2025 style, obtained from the official ICCV 2025 Author
  Kit distributed via iccv.thecvf.com; bundled unmodified for paper formatting.
- `axessibility.sty` — axessibility v3.0 from CTAN
  (<https://ctan.org/pkg/axessibility>), licensed LPPL 1.3, copyright 2018-2020
  by the axessibility authors; bundled unmodified (used with the `accsupp`
  option).
- `aaai25.sty` / `aaai25.bst` — AAAI-25 LaTeX style files from the official
  AAAI Author Kit 2025 (<https://aaai.org/authorkit25-2/>), copyright AAAI.
  They are provided "as is" for preparing AAAI submissions and must not be
  modified per the notice in the style file.
- `arxiv.sty` — kourgeorge/arxiv-style LaTeX style (arXiv preprint style),
  obtained from <https://github.com/kourgeorge/arxiv-style> (MIT, Copyright (c)
  2020 George Kour). Bundled unmodified.

The benchmark papers themselves, their LaTeX sources, figures, tables, and
code remain the intellectual property of their respective authors and are
governed by their original licenses. They are never committed to this
repository; they are downloaded on demand from the upstream Hugging Face
dataset `hal-utokyo/PaperWrite-Bench`.
