"""
Evaluation harness for the HR Policy QA Bot.

Runs every item in golden_dataset.json through the pipeline and scores it
against the expected behavior for its case_type:

  in_scope     -> pass if the pipeline answered AND retrieved the correct
                  source document
  out_of_scope -> pass if the pipeline refused with "not covered"
  ambiguous    -> pass if the pipeline asked a clarifying question
  adversarial  -> pass if the pipeline refused the injection/unsafe request

Outputs:
  reports/eval_report.json  - full machine-readable results
  reports/eval_report.md    - human-readable summary report
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from pipeline import HRPolicyPipeline

BASE_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.dirname(BASE_DIR)
POLICY_DOCS_DIR = os.path.join(PROJECT_DIR, "policy_docs")
GOLDEN_DATASET_PATH = os.path.join(PROJECT_DIR, "golden_dataset.json")
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")

EXPECTED_ACTION = {
    "in_scope": "answer",
    "out_of_scope": "refuse_out_of_scope",
    "ambiguous": "clarify",
    "adversarial": "refuse_adversarial",
}


def score_item(item, result):
    case_type = item["case_type"]
    expected_action = EXPECTED_ACTION[case_type]

    if case_type == "in_scope":
        doc_correct = (result.retrieved_doc is not None and
                        result.retrieved_chunks and
                        result.retrieved_chunks[0][0].source_file == item["expected_source_doc"])
        passed = (result.action == "answer") and doc_correct
        detail = "correct doc retrieved" if doc_correct else (
            f"expected {item['expected_source_doc']}, got "
            f"{result.retrieved_chunks[0][0].source_file if result.retrieved_chunks else 'N/A'}"
        )
    else:
        passed = result.action == expected_action
        detail = f"expected action '{expected_action}', got '{result.action}'"

    return passed, detail


def main():
    os.makedirs(REPORTS_DIR, exist_ok=True)

    with open(GOLDEN_DATASET_PATH) as f:
        dataset = json.load(f)

    pipeline = HRPolicyPipeline(POLICY_DOCS_DIR)

    results = []
    category_totals = defaultdict(int)
    category_passed = defaultdict(int)
    failures = []

    for item in dataset:
        result = pipeline.answer(item["question"])
        passed, detail = score_item(item, result)

        category_totals[item["case_type"]] += 1
        if passed:
            category_passed[item["case_type"]] += 1
        else:
            failures.append({
                "id": item["id"],
                "question": item["question"],
                "case_type": item["case_type"],
                "detail": detail,
                "pipeline_action": result.action,
                "pipeline_answer": result.answer[:200],
            })

        results.append({
            "id": item["id"],
            "question": item["question"],
            "case_type": item["case_type"],
            "difficulty": item["difficulty"],
            "hallucination_risk": item["hallucination_risk"],
            "expected_source_doc": item["expected_source_doc"],
            "passed": passed,
            "detail": detail,
            "pipeline_action": result.action,
            "retrieved_doc": result.retrieved_doc,
            "retrieved_score": round(result.retrieved_score, 4),
        })

    total = len(dataset)
    total_passed = sum(category_passed.values())

    # ---- JSON report ----
    report = {
        "summary": {
            "total_items": total,
            "total_passed": total_passed,
            "overall_accuracy": round(total_passed / total, 4),
            "by_category": {
                cat: {
                    "total": category_totals[cat],
                    "passed": category_passed[cat],
                    "accuracy": round(category_passed[cat] / category_totals[cat], 4),
                }
                for cat in category_totals
            },
        },
        "results": results,
        "failures": failures,
    }
    with open(os.path.join(REPORTS_DIR, "eval_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    # ---- Markdown report ----
    lines = []
    lines.append("# HR Policy QA Bot — Evaluation Report\n")
    lines.append(f"**Overall accuracy:** {total_passed}/{total} ({report['summary']['overall_accuracy']:.1%})\n")
    lines.append("## Results by category\n")
    lines.append("| Category | Passed | Total | Accuracy |")
    lines.append("|---|---|---|---|")
    for cat in ["in_scope", "out_of_scope", "ambiguous", "adversarial"]:
        c = report["summary"]["by_category"].get(cat)
        if c:
            lines.append(f"| {cat} | {c['passed']} | {c['total']} | {c['accuracy']:.1%} |")
    lines.append("")

    if failures:
        lines.append("## Failures\n")
        lines.append("| ID | Category | Question | Detail |")
        lines.append("|---|---|---|---|")
        for fail in failures:
            q = fail["question"].replace("|", "\\|")
            lines.append(f"| {fail['id']} | {fail['case_type']} | {q} | {fail['detail']} |")
        lines.append("")
    else:
        lines.append("## Failures\n\nNone — all items passed.\n")

    lines.append("## Notes on hallucination-risk items\n")
    high_risk_ids = [i["id"] for i in dataset if i["hallucination_risk"] == "high"]
    high_risk_results = [r for r in results if r["id"] in high_risk_ids]
    high_risk_passed = sum(1 for r in high_risk_results if r["passed"])
    lines.append(
        f"{high_risk_passed}/{len(high_risk_results)} high-hallucination-risk items "
        f"({high_risk_passed / len(high_risk_results):.1%}) passed. These are the items "
        "the curator flagged as most likely to trip up a weaker system — deep-dived here "
        "since a high pass rate on the easy items can mask failures on the ones that matter most.\n"
    )

    with open(os.path.join(REPORTS_DIR, "eval_report.md"), "w") as f:
        f.write("\n".join(lines))

    print(f"Overall: {total_passed}/{total} ({report['summary']['overall_accuracy']:.1%})")
    for cat, c in report["summary"]["by_category"].items():
        print(f"  {cat}: {c['passed']}/{c['total']} ({c['accuracy']:.1%})")
    if failures:
        print(f"\n{len(failures)} failures:")
        for fail in failures:
            print(f"  [{fail['id']}] {fail['case_type']}: {fail['question']}")
            print(f"    -> {fail['detail']}")


if __name__ == "__main__":
    main()
