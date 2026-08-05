from scripts.summarize_paired_sweep import exact_mcnemar_pvalue


def test_exact_mcnemar_two_sided_small_counts():
    assert exact_mcnemar_pvalue(0, 0) == 1.0
    assert exact_mcnemar_pvalue(2, 1) == 1.0
    assert exact_mcnemar_pvalue(5, 0) == 0.0625
