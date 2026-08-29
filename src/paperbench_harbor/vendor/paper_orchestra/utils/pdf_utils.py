# Copyright 2026 Google LLC (upstream logic); shim adapted by paperbench-harbor.
# Licensed under the Apache License, Version 2.0 (the "License").

"""PDF text backend for the PaperOrchestra utils.

Keeps the official `load_paper` / `get_paper_references_from_pdf` behavior
(reference extraction prompt included verbatim) but extracts PDF text with
pdftotext instead of pymupdf/pypdf.
"""

import subprocess


def load_paper(pdf_path, num_pages=None, min_size=100):
    command = ["pdftotext", "-layout", pdf_path, "-"]
    if num_pages:
        command = ["pdftotext", "-layout", "-f", "1", "-l", str(num_pages), pdf_path, "-"]
    result = subprocess.run(command, capture_output=True, text=True)
    text = result.stdout or ""
    if len(text) < min_size:
        raise Exception("Text too short")
    return text


def has_blacklist_words(text: str):
    blacklists = ["corresponding author"]
    for word in blacklists:
        if word in text.lower():
            return True
    return False


papaer_text_to_reference_text_prompt_template = """
You are a specialized academic data extraction engine. Your task is to extract the "References" or "Bibliography" section from the raw text of a research paper and return it in a specific single-line string format.

### INPUT DATA
You will receive raw text extracted from a PDF. This text may contain:
- Noise (headers, footers, page numbers).
- Arbitrary line breaks (sentences broken across lines).
- The body of the paper followed by the references.

### INSTRUCTIONS
1. **Locate:** Find the start of the "References" or "Bibliography" section. Ignore all text preceding this section.
2. **Extract:** Identify individual reference entries. These typically start with bracketed numbers (e.g., [1], [2]) or bare numbers (1., 2.).
3. **Clean:** - Merge multi-line citations into a single line. 
   - Remove any page numbers or running headers that interrupt a citation.
4. **Format:** Output the citations as a single continuous string. Ensure every citation starts with its bracketed ID (e.g., `[1]`). If the source text uses `1.` format, convert it to `[1]`.

### OUTPUT FORMAT
Your output must be a single string containing ONLY the references, formatted exactly as follows:
"[1] First citation text [2] Second citation text [3] Third citation text [4] ... "

### CONSTRAINTS
- Do NOT output JSON, Markdown lists, or XML.
- Do NOT output the word "References" or "Bibliography" at the start.
- Do NOT output any conversational text (e.g., "Here are the references").
- Do NOT change the content/wording of the citation titles or authors, only clean up the whitespace.

Here is the paper text:
[PAPER CONTENT]
{paper_text}
[END PAPER CONTENT]
"""


def extract_reference_from_pdf_text(
    paper_text: str, model_name: str = "gemini-3.1-pro-preview"
) -> str:
    from utils.llm_backend_utils import call_llm_with_text_prompt

    instructions = papaer_text_to_reference_text_prompt_template.format(
        paper_text=paper_text
    )
    response_dict = call_llm_with_text_prompt(
        prompt=instructions,
        model_name=model_name,
        check_parsed_response_not_none=False,
        return_json=False,
    )
    return response_dict["raw_response"].strip()


def get_paper_references_from_pdf(
    pdf_path: str, model_name: str = "gemini-3.1-pro-preview"
):
    try:
        paper_text = load_paper(pdf_path)
        reference_text = extract_reference_from_pdf_text(
            paper_text, model_name=model_name
        )
        if reference_text:
            return reference_text
    except Exception as error:
        print(f"Failed to extract references from {pdf_path}: {error}")
    return None
