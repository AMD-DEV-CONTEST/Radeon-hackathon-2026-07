# Seven-city animated public demo

Serve this directory over HTTP:

```bash
python -m http.server 8765 --directory public_demo
```

Then open `http://127.0.0.1:8765/web/viewer.html?city=kumamoto_agents&frame=18`.

Available city keys: `los_angeles`, `naples`, `wellington`, `l_aquila`, `noto`, `kumamoto_agents`, and `kathmandu`.

The payloads are archived synthetic scenarios for reproducible review. They are not observed individual trajectories or official plans.
