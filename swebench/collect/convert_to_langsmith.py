#!/usr/bin/env python3

"""Convert SWE-bench task instances to LangSmith dataset format.

LangSmith is LangChain's platform for evaluating and monitoring LLM applications.
This script converts SWE-bench task instances (JSONL format) to LangSmith's
dataset format for evaluation purposes.

Usage:
    python convert_to_langsmith.py <input_file.jsonl> <output_file.jsonl>

    # Or use as module:
    python -m swebench.collect.convert_to_langsmith <input> <output>

Example:
    python convert_to_langsmith.py task_instances.jsonl langsmith_dataset.jsonl
"""

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def convert_instance_to_langsmith(
    instance: dict, include_test_patch: bool = True
) -> dict:
    """
    Convert a single SWE-bench task instance to LangSmith format.

    Args:
        instance: SWE-bench task instance dictionary
        include_test_patch: Whether to include test patch in outputs

    Returns:
        Dictionary in LangSmith format with inputs, outputs, and metadata
    """
    # Inputs: Information given to the model
    inputs = {
        "problem_statement": instance.get("problem_statement", ""),
        "repo": instance.get("repo", ""),
        "base_commit": instance.get("base_commit", ""),
        "hints_text": instance.get("hints_text", ""),
    }

    # Outputs: Expected/reference solution
    outputs = {
        "patch": instance.get("patch", ""),
    }

    if include_test_patch:
        outputs["test_patch"] = instance.get("test_patch", "")

    # Metadata: Additional context and identifiers
    metadata = {
        "instance_id": instance.get("instance_id", ""),
        "pull_number": instance.get("pull_number"),
        "issue_numbers": instance.get("issue_numbers", []),
        "created_at": instance.get("created_at", ""),
        "source": "swe-bench",
        "platform": (
            "gitlab"
            if "/" in instance.get("repo", "")
            and instance.get("repo", "").count("/") > 1
            else "github"
        ),
    }

    return {
        "inputs": inputs,
        "outputs": outputs,
        "metadata": metadata,
    }


def convert_file(
    input_file: str,
    output_file: str,
    include_test_patch: bool = True,
    overwrite: bool = False,
) -> None:
    """
    Convert an entire SWE-bench task instances file to LangSmith format.

    Args:
        input_file: Path to input JSONL file (SWE-bench format)
        output_file: Path to output JSONL file (LangSmith format)
        include_test_patch: Whether to include test patches in outputs
        overwrite: Whether to overwrite existing output file
    """
    input_path = Path(input_file)
    output_path = Path(output_file)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_file}. Use --overwrite to replace it."
        )

    converted_count = 0
    total_count = 0

    logger.info(f"Converting {input_file} to LangSmith format...")

    with open(input_path, "r") as infile, open(output_path, "w") as outfile:
        for line_num, line in enumerate(infile, 1):
            total_count += 1

            try:
                instance = json.loads(line)
                langsmith_format = convert_instance_to_langsmith(
                    instance, include_test_patch
                )

                # Write as single-line JSON
                json.dump(langsmith_format, outfile)
                outfile.write("\n")

                converted_count += 1

                if converted_count % 10 == 0:
                    logger.info(f"Converted {converted_count} instances...")

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON on line {line_num}: {e}")
                continue
            except Exception as e:
                logger.error(f"Failed to convert instance on line {line_num}: {e}")
                continue

    logger.info(f"✅ Successfully converted {converted_count}/{total_count} instances")
    logger.info(f"Output saved to: {output_file}")

    # Print sample
    logger.info("\nSample converted instance:")
    with open(output_path, "r") as f:
        sample = json.loads(f.readline())
        logger.info(f"  Inputs keys: {list(sample['inputs'].keys())}")
        logger.info(f"  Outputs keys: {list(sample['outputs'].keys())}")
        logger.info(f"  Metadata keys: {list(sample['metadata'].keys())}")
        logger.info(f"  Instance ID: {sample['metadata']['instance_id']}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "input_file",
        type=str,
        help="Path to input JSONL file (SWE-bench task instances format)",
    )
    parser.add_argument(
        "output_file",
        type=str,
        help="Path to output JSONL file (LangSmith dataset format)",
    )
    parser.add_argument(
        "--no-test-patch",
        action="store_true",
        help="Exclude test patches from outputs (only include solution patch)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it already exists",
    )

    args = parser.parse_args()

    try:
        convert_file(
            args.input_file,
            args.output_file,
            include_test_patch=not args.no_test_patch,
            overwrite=args.overwrite,
        )
    except Exception as e:
        logger.error(f"Conversion failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
