# Copyright 2026 Google LLC (upstream logic); shim adapted by paperbench-harbor.
# Licensed under the Apache License, Version 2.0 (the "License").

"""OpenAI-compatible backend for the PaperOrchestra Gemini utils.

Keeps the official call signatures and JSON parsing, but routes model calls
through litellm so the autoraters can run against any OpenAI-compatible
judge endpoint (JUDGE_MODEL, OPENAI_API_KEY, OPENAI_API_BASE). The
`model_name` argument is ignored in favor of JUDGE_MODEL.
"""

import json
import os
import re

import litellm

litellm.drop_params = True
litellm.suppress_debug_info = True


def _judge_model() -> str:
    return os.environ.get("JUDGE_MODEL", "gpt-5.4")


def parse_gemini_json_results(response: str):
    if not response or not isinstance(response, str):
        return None

    json_pattern = r"```json(.*?)```"
    matches = re.findall(json_pattern, response, re.DOTALL)

    if not matches:
        json_pattern = r"(\{.*\}|\[.*\])"
        matches = re.findall(json_pattern, response, re.DOTALL)

    for json_string in matches:
        json_string = json_string.strip()
        try:
            parsed_json = json.loads(json_string)
            return parsed_json
        except json.JSONDecodeError:
            try:
                json_string_clean = re.sub(r"[\x00-\x1F\x7F]", "", json_string)
                json_string_clean = re.sub(r",\s*([\]}])", r"\1", json_string_clean)
                json_string_clean = re.sub(
                    r'\\(?![\\"/bfnrtu])', r"\\\\", json_string_clean
                )

                parsed_json = json.loads(json_string_clean)
                return parsed_json
            except json.JSONDecodeError:
                continue
    return None


def call_gemini_with_text_prompt(
    prompt: str,
    model_name: str,
    result_parsing_func=parse_gemini_json_results,
    generation_configs: dict = {},
    check_parsed_response_not_none: bool = True,
    max_retries: int = 5,
    base_interval_sec: int = 5,
):
    """Same contract as PaperOrchestra's utils.gemini_utils."""
    import time

    system_instruction = generation_configs.get("system_instruction")
    temperature = generation_configs.get("temperature", 0.0)

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    raw_response = None
    parsed_response = None
    for attempt in range(max_retries):
        try:
            response = litellm.completion(
                model=_judge_model(),
                messages=messages,
                temperature=temperature,
            )
            raw_response = response.choices[0].message.content
            if not raw_response:
                raise ValueError("Incomplete response from judge or empty text")
            parsed_response = result_parsing_func(raw_response)
            if check_parsed_response_not_none and parsed_response is None:
                raise ValueError("Could not parse JSON response from judge")
            break
        except Exception as error:
            print(f"Attempt {attempt + 1}/{max_retries} failed: {error}")
            time.sleep(base_interval_sec * (2**attempt))
    return {"raw_response": raw_response, "parsed_response": parsed_response}
