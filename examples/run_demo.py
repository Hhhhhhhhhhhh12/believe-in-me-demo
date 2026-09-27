from believe_engine.metrics import summarize_results
from believe_engine.runner import run_match


def main() -> None:
    results = [run_match(seed=seed) for seed in range(10)]
    for result in results:
        print(
            f"seed={result.seed} status={result.status} "
            f"winner={result.winner_id} turns={result.turn_count}"
        )
    print(summarize_results(results))


if __name__ == "__main__":
    main()
