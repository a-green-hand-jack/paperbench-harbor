# Copyright 2026 Google LLC (upstream logic); shim adapted by paperbench-harbor.
# Licensed under the Apache License, Version 2.0 (the "License").

"""OpenAI-compatible backend for the PaperOrchestra LLM utils.

Keeps the official signatures of `call_llm_with_text_prompt` and
`call_llm_with_pdf`; PDFs are converted to text via `load_paper` and all
calls are routed through litellm to the JUDGE_MODEL endpoint.
"""

import os
from typing import Any, Callable, Dict, Optional

import litellm

from utils.gemini_utils import call_gemini_with_text_prompt, parse_gemini_json_results
from utils.pdf_utils import load_paper

litellm.drop_params = True
litellm.suppress_debug_info = True


def _judge_model() -> str:
    return os.environ.get("JUDGE_MODEL", "gpt-5.4")


def identity_parse(response: str) -> str:
    return response


def get_llm_parser(model_name: str, return_json: bool = True) -> Callable:
    if not return_json:
        return identity_parse
    return parse_gemini_json_results


def call_llm_with_text_prompt(
    prompt: str,
    model_name: str,
    generation_configs: Optional[Dict[str, Any]] = None,
    check_parsed_response_not_none: bool = True,
    return_json: bool = True,
    result_parsing_func: Optional[Callable] = None,
) -> Dict[str, Any]:
    parser = (
        result_parsing_func
        if result_parsing_func is not None
        else get_llm_parser(model_name, return_json)
    )
    return call_gemini_with_text_prompt(
        prompt=prompt,
        model_name=_judge_model(),
        result_parsing_func=parser,
        generation_configs=generation_configs or {},
        check_parsed_response_not_none=check_parsed_response_not_none,
    )


def call_llm_with_pdf(
    pdf_path: str,
    prompt: str,
    model_name: str,
    system_instruction: Optional[str] = None,
    temperature: float = 0.7,
    check_parsed_response_not_none: bool = True,
    return_json: bool = True,
    result_parsing_func: Optional[Callable] = None,
) -> Dict[str, Any]:
    parser = (
        result_parsing_func
        if result_parsing_func is not None
        else get_llm_parser(model_name, return_json)
    )
    paper_text = load_paper(pdf_path, min_size=100)
    full_prompt = f"Paper Content:\n{paper_text}\n\nTask:\n{prompt}"
    return call_gemini_with_text_prompt(
        prompt=full_prompt,
        model_name=_judge_model(),
        result_parsing_func=parser,
        generation_configs={
            "temperature": temperature,
            "system_instruction": system_instruction,
        },
        check_parsed_response_not_none=check_parsed_response_not_none,
    )
