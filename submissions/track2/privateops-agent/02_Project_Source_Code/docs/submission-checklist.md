# Submission Checklist

The authoritative checklist is `submission/final-checklist.md`. It separates repository work already produced and automatically verified from account-bound actions: Radeon Cloud execution, benchmark evidence, video hosting, event registration, official repository fork, and final pull request.

Run before packaging:

```powershell
python scripts\verify_submission.py
python -m unittest discover -s tests -v
python scripts\smoke_test.py
```
