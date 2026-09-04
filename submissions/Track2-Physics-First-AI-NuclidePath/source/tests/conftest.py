def pytest_addoption(parser):
    parser.addoption(
        "--run-external-solver",
        action="store_true",
        default=False,
        help="run fail-closed tests against an explicitly configured real solver",
    )
