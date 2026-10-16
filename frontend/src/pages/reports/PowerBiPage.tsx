import { useState } from "react";
import { send } from "@/api/client";
import { Alert, Button, Card, ErrorState, Loading, PageHeader, useToast } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDateTime } from "@/lib/format";

interface Dataset { name: string; description: string; key: string; url: string }

export default function PowerBiPage() {
  const toast = useToast();
  const datasets = useApi<Dataset[]>("/bi/datasets/");
  const token = useApi<{ has_token: boolean; created: string | null }>("/bi/token/");
  const [issued, setIssued] = useState<string | null>(null);
  const origin = window.location.origin;
  if (datasets.error) return <ErrorState error={datasets.error} onRetry={datasets.reload} />;
  return (
    <div>
      <PageHeader title="Power BI access" subtitle="Read-only star-schema datasets for Power BI Desktop. See docs/powerbi/ for the model, DAX measures and refresh guide." />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="Connection options" className="xl:col-span-2">
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            <li><strong>Recommended - PostgreSQL connector:</strong> connect Power BI Desktop to the database with a dedicated read-only role that can only
              <code className="mx-1 rounded bg-sunken px-1">SELECT</code> from schema <code className="rounded bg-sunken px-1">bi</code> (script in <code>docs/powerbi/create_bi_reader.sql</code>).</li>
            <li><strong>Web connector:</strong> use the read-only API below with an <code>Authorization: Token …</code> header. Tokens work only on <code>/api/bi/</code> endpoints.</li>
            <li><strong>Files:</strong> download CSV/XLSX from the Report center for ad-hoc analysis.</li>
          </ol>
          <p className="mt-3 text-xs text-muted">No Power BI report has been published to the Power BI Service from this environment; the .pbix layout is documented for you to build.</p>
        </Card>
        <Card title="Personal API token">
          {token.loading ? <Loading /> : (
            <>
              <p className="mb-2 text-sm">{token.data?.has_token ? `Active token issued ${fmtDateTime(token.data.created)}.` : "No token issued."}</p>
              {issued && <div className="mb-2"><Alert tone="warn" title="Copy it now - it will not be shown again"><code className="break-all text-xs">{issued}</code></Alert></div>}
              <div className="flex gap-2">
                <Button variant="primary" size="sm" onClick={async () => { const r = await send<{ token: string }>("post", "/bi/token/"); setIssued(r.token); token.reload(); }}>
                  {token.data?.has_token ? "Rotate token" : "Issue token"}</Button>
                {token.data?.has_token && <Button size="sm" onClick={async () => { await send("delete", "/bi/token/"); setIssued(null); token.reload(); toast.success("Token revoked"); }}>Revoke</Button>}
              </div>
            </>
          )}
        </Card>
      </div>
      <Card title="Datasets" className="mt-4" bodyClass="p-0">
        {!datasets.data ? <Loading /> : (
          <table className="w-full text-sm"><thead className="border-b border-border bg-raised"><tr><th className="th">Dataset</th><th className="th">Description</th><th className="th">Key</th><th className="th">Endpoint</th></tr></thead>
            <tbody>{datasets.data.map((d) => (
              <tr key={d.name} className="border-b border-border last:border-0"><td className="td font-mono text-xs">bi.{d.name}</td><td className="td">{d.description}</td>
                <td className="td font-mono text-xs">{d.key}</td>
                <td className="td"><a className="link text-xs" href={`${d.url}?output=csv`}>{origin}{d.url}</a></td></tr>))}</tbody></table>
        )}
      </Card>
    </div>
  );
}
