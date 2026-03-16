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
    parser.add_argument("-t", "--resume-timestamp", help="Timestamp to resume an existing experiment (format: YYYYMMDD-HHMMSS). Overrides the auto-generated timestamp.")
    parser.add_argument("--instance-ids", nargs="+", help="List of instance IDs to evaluate. If not provided, evaluates all instances.")
    parser.add_argument("--reevaluate", action="store_true", help="Re-evaluate cached patches from a previous experiment. Requires --resume-timestamp (-t) to identify the experiment.")

    args = parser.parse_args()

    if args.reevaluate:
        if not args.resume_timestamp:
            parser.error("--reevaluate requires --resume-timestamp (-t) to identify the cached experiment")
        evaluator = AgentEvaluator()
        evaluator.reevaluate(agent_names=args.agents, instance_ids=args.instance_ids)
    elif args.evaluate:
        evaluator = AgentEvaluator()
        evaluator.evaluate(agent_names=args.agents, instance_ids=args.instance_ids)
    else:
        runner = DockerAgentRunner(test_only=args.test_only)
        runner.run()

if __name__ == "__main__":
    main()
