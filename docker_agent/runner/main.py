"""Main entry point for docker_agent"""

import argparse
from docker_agent.runner.docker_runner import DockerAgentRunner
from docker_agent.evaluation.evaluator import AgentEvaluator


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Docker Agent Runner")
    parser.add_argument("--test-only", action="store_true", help="Only run tests, skip environment configuration and image saving")
    parser.add_argument("--evaluate", action="store_true", help="Run evaluation mode")
    parser.add_argument("--agents", nargs="+", help="List of agent names to evaluate (Now only Trae-agent is supported)")

    args = parser.parse_args()

    if args.evaluate:
        evaluator = AgentEvaluator()
        evaluator.evaluate(agent_names=args.agents)
    else:
        runner = DockerAgentRunner(test_only=args.test_only)
        runner.run()

if __name__ == "__main__":
    main()
