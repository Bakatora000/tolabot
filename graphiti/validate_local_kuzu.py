from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.driver.kuzu_driver import KuzuDriver
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient


def build_llm_config() -> LLMConfig:
    return LLMConfig(
        api_key=os.getenv("GRAPHITI_LLM_API_KEY", "dummy"),
        base_url=os.getenv("GRAPHITI_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
        model=os.getenv("GRAPHITI_LLM_MODEL", "dummy-model"),
    )


def build_embedder_config() -> OpenAIEmbedderConfig:
    return OpenAIEmbedderConfig(
        api_key=os.getenv("GRAPHITI_EMBEDDING_API_KEY", "dummy"),
        base_url=os.getenv("GRAPHITI_EMBEDDING_BASE_URL", os.getenv("GRAPHITI_LLM_BASE_URL", "http://127.0.0.1:11434/v1")),
        embedding_model=os.getenv("GRAPHITI_EMBEDDING_MODEL", "dummy-embed"),
    )


async def run_validation(db_path: Path, reset: bool) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    llm = OpenAIGenericClient(config=build_llm_config())
    embedder = OpenAIEmbedder(config=build_embedder_config())
    reranker = OpenAIRerankerClient(config=build_llm_config())
    driver = KuzuDriver(db=str(db_path))
    graphiti = Graphiti(graph_driver=driver, llm_client=llm, embedder=embedder, cross_encoder=reranker)
    try:
        await graphiti.build_indices_and_constraints(delete_existing=reset)
        print(f"graphiti_kuzu_init_ok db={db_path}")
    finally:
        await graphiti.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a local Graphiti + Kuzu setup.")
    parser.add_argument(
        "--db",
        default=os.getenv("GRAPHITI_KUZU_DB_PATH", "graphiti/data/graphiti.kuzu"),
        help="Path to the local Kuzu database file.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Recreate Graphiti indices/constraints from scratch.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_validation(Path(args.db), reset=args.reset))


if __name__ == "__main__":
    main()
