# pycalc demo project

This is the demo task used by the `radeon-fix` video. It is a small Python
package with three deliberate bugs across two modules.

Issue given to the agent:

> pycalc has three bugs:
> 1. `mode` breaks ties by returning the first encountered value instead of
>    the smaller value;
> 2. `normalize` scales by the maximum instead of the min-max range, crashes
>    when the maximum is 0, and does not handle all-equal inputs;
> 3. `report.summary_text` only prints the first five normalized values
>    instead of all of them.
> Fix all three so every test in `tests/` passes.

Run the public check with:

```bash
python -m pytest -q
```
