import { useApi, type OpsStatus } from "../api";
import { SOURCE_LABEL, timeAgo } from "../format";
import { ErrorNote, Loading, PageHeader, Panel, Tag } from "../ui";

export default function Status() {
  const ops = useApi<OpsStatus>("/ops/status", 30_000);
  if (ops.error) return <ErrorNote error={ops.error} onRetry={ops.reload} />;
  if (!ops.data) return <Loading />;
  const src = Object.entries(ops.data.collectors?.sources ?? {});
  const st = ops.data.store;

  return (
    <>
      <PageHeader eyebrow="Workspace" title="Data sources" />
      <div className="grid gap-4 sm:grid-cols-3">
        {[
          ["Documents", st.documents],
          ["Events", st.events],
          ["Signals", st.signals],
        ].map(([k, v]) => (
          <div key={k} className="rounded-xl border border-line bg-ink-2 p-5">
            <div className="text-sm text-mute">{k}</div>
            <div className="mt-2 font-serif text-4xl text-bone">{Number(v).toLocaleString()}</div>
          </div>
        ))}
      </div>
      <Panel className="mt-6" title="Collectors" sub={ops.data.collectors ? `Status written ${timeAgo(ops.data.collectors.updated_at)}` : "No status file yet"}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-mute">
              <tr>
                {["Source", "Status", "Interval", "Runs", "Items added", "Last run", "Failures"].map((h) => (
                  <th key={h} className="pb-2 pr-4 font-normal">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {src.map(([name, s]) => {
                const ok = s.last_status === "ok" && !s.consecutive_failures;
                return (
                  <tr key={name}>
                    <td className="py-3 pr-4 text-bone">{SOURCE_LABEL[name] ?? name}</td>
                    <td className="py-3 pr-4">
                      <Tag tone={ok ? "sage" : "ember"}>{s.paused_until ? "paused" : s.last_status}</Tag>
                    </td>
                    <td className="py-3 pr-4 text-mute">{s.interval_minutes ? `${s.interval_minutes} min` : "stream"}</td>
                    <td className="py-3 pr-4 font-mono text-mute">{s.runs.toLocaleString()}</td>
                    <td className="py-3 pr-4 font-mono text-mute">{s.inserted_total.toLocaleString()}</td>
                    <td className="py-3 pr-4 text-mute">{s.last_run ? timeAgo(s.last_run) : "never"}</td>
                    <td className="py-3 font-mono text-mute">{s.consecutive_failures}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {src.some(([, s]) => s.last_error) && (
          <ul className="mt-4 space-y-1 text-xs text-ember-bright">
            {src.filter(([, s]) => s.last_error).map(([n, s]) => (
              <li key={n}>
                {n}: {s.last_error}
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <p className="mt-6 text-xs text-mute">
        Only public sources are collected. Thresholds, weights and shocks are configuration files in the repository (config/*.yaml), each tied to
        an entry in the assumptions register.
      </p>
    </>
  );
}
