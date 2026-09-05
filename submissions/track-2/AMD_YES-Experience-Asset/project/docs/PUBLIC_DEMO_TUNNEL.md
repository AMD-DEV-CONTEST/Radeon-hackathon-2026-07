# Radeon Cloud Public Demo Tunnel

Last verified: 2026-07-22

## Decision

The project remains private by default:

```text
vLLM API       -> 127.0.0.1:8000, never exposed directly
Agent Web UI   -> 127.0.0.1:<demo-port>
rc-tunnel      -> optional public HTTPS URL for the authenticated Web UI only
SSH / VS Code  -> Radeon Cloud's separate SSH endpoint, not rc-tunnel
```

The public tunnel is useful for a judge-facing demo, but it is not required for
VS Code Remote SSH, Codex, Claude Code, or normal development.

The approved E9 access/session/queue behavior is defined in
[`kinnyu/E9_PUBLIC_DEMO_ACCESS_AND_QUEUE_REQUIREMENTS.md`](kinnyu/E9_PUBLIC_DEMO_ACCESS_AND_QUEUE_REQUIREMENTS.md).
It is a deployment/WebUI adapter and must not change the Experience Asset
business workflows or canonical product schema.

## Official constraints

The official Radeon Cloud guide now states:

- only newly created Notebook Pods support the feature;
- only HTTP and WebSocket services bound to `127.0.0.1` are supported;
- the local port must be between `1024` and `65535` and not reserved;
- the platform assigns a domain like `rc-<random>.radeon.firstdg.ai`;
- one Notebook Pod can expose only one port at a time;
- TCP, UDP, SSH, database ports, and custom full domains are unsupported;
- after recreating the Notebook, install and expose must be run again;
- the generated URL is publicly reachable, so the application must enforce
  authentication and must not expose an unauthenticated admin page.

## Safe setup

First make the Web UI listen only on localhost. Example:

```bash
APP_HOST=127.0.0.1
APP_PORT=7860
```

Verify the local service before touching the public tunnel:

```bash
curl --fail http://127.0.0.1:7860/
```

Install the platform tool inside the Notebook:

```bash
/var/run/secrets/frp-self-service/install
export PATH="$HOME/.local/bin:$PATH"
rc-tunnel version
```

Do not request, create, copy, or edit platform FRP keys. Do not copy
`~/.local/state/rc-tunnel` to another Pod.

## Publication gate

Creating a tunnel publishes a service to the internet. A coding agent must not
run this command without an explicit human instruction made after the local
service and authentication have been verified:

```bash
rc-tunnel expose --port 7860
```

Immediately before that external action, verify all of the following on the
exact commit intended for the demo:

- the temporary access-code session is enabled with non-default secrets;
- the bounded queue is enabled with one worker and capacity six;
- missing/invalid sessions, duplicate clicks, a full queue and adapter restart
  have passed their E9 checks;
- the final demo path shows real `QUEUED`, `RUNNING`, user-input and terminal
  states without a fabricated ETA;
- only approved public/synthetic demo content is present; and
- the recorded local demo has passed as the fallback.

After publication:

```bash
rc-tunnel status
rc-tunnel logs --lines 100
```

Before the demo ends or the pod is destroyed:

```bash
rc-tunnel stop
```

Stopping invalidates the public URL immediately. The released prefix is frozen
for 24 hours according to the official guide.

## Security checklist

- expose the Web UI, never the raw vLLM endpoint;
- require login or a strong, temporary access token;
- do not place secrets in URL query parameters;
- disable file browsing, shell access, arbitrary URL fetches, and admin routes;
- enforce tool permissions in the Agent runtime;
- use non-sensitive demo data;
- stop the tunnel after the judging session;
- record only the domain and test time in evidence, never FRP configuration or
  platform keys.
