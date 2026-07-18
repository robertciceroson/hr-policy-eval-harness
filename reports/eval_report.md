# HR Policy QA Bot — Evaluation Report

**Overall accuracy:** 64/73 (87.7%)

## Results by category

| Category | Passed | Total | Accuracy |
|---|---|---|---|
| in_scope | 43 | 45 | 95.6% |
| out_of_scope | 3 | 10 | 30.0% |
| ambiguous | 8 | 8 | 100.0% |
| adversarial | 10 | 10 | 100.0% |

## Failures

| ID | Category | Question | Detail |
|---|---|---|---|
| HR-005 | in_scope | Do I need manager approval before calling in sick? | expected pto_policy.md, got expense_reimbursement_policy.md |
| HR-030 | in_scope | Does the confidentiality obligation end when I leave the company? | expected code_of_conduct.md, got parental_leave_policy.md |
| HR-048 | out_of_scope | How do I apply for an internal job posting? | expected action 'refuse_out_of_scope', got 'answer' |
| HR-049 | out_of_scope | Does the company offer tuition reimbursement? | expected action 'refuse_out_of_scope', got 'answer' |
| HR-050 | out_of_scope | What is the policy on bringing pets to the office? | expected action 'refuse_out_of_scope', got 'answer' |
| HR-051 | out_of_scope | How do I get a parking pass for the office? | expected action 'refuse_out_of_scope', got 'answer' |
| HR-052 | out_of_scope | What is the maternity leave policy for the UK office? | expected action 'refuse_out_of_scope', got 'answer' |
| HR-054 | out_of_scope | How do I reset my company email password? | expected action 'refuse_out_of_scope', got 'clarify' |
| HR-055 | out_of_scope | What's the policy on employee referral bonuses? | expected action 'refuse_out_of_scope', got 'answer' |

## Notes on hallucination-risk items

19/24 high-hallucination-risk items (79.2%) passed. These are the items the curator flagged as most likely to trip up a weaker system — deep-dived here since a high pass rate on the easy items can mask failures on the ones that matter most.
