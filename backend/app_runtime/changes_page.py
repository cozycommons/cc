import html

from fastapi.responses import HTMLResponse


def render_changes_page(name, result=None, error=None, status_code=200):
    def escape(value):
        return html.escape(str(value), quote=True)

    body = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<link rel="icon" type="image/svg+xml" href="/favicon.svg">',
        f"<title>Changes · {escape(name)} · Apps</title>",
        "<style>body{margin:0;background:#f7f6f1;color:#292b26;font:15px/1.55 system-ui,sans-serif}main{max-width:1000px;margin:40px auto;padding:0 24px}a{color:#375c49}section{margin:24px 0;padding:16px 0;border-top:1px solid #d9d6ce}h1{font-size:30px}h2{font-size:19px}code,pre{font:13px ui-monospace,monospace}pre{overflow:auto;padding:16px;background:#eeede7;border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere}.error{padding:12px;background:#f2e4dd;border-radius:6px}.files{border-collapse:collapse;width:100%}.files td{padding:7px;border-bottom:1px solid #ddd;text-align:left}.muted{color:#696b63}</style>",
        "</head><body><main>",
        '<p><a href="/">Apps</a></p>',
        f"<h1>Changes · <code>{escape(name)}</code></h1>",
    ]
    if error:
        body.append(f'<p class="error">{escape(error)}</p>')
    elif result:
        if result.get("truncated"):
            body.append(
                '<p class="error">Inspection reached its limits; this view may be partial.</p>'
            )
        repositories = result.get("repositories", [])
        if result.get("error"):
            body.append(
                '<p class="error">Git inspection is unavailable for this workspace.</p>'
            )
        elif not repositories:
            message = (
                "No repositories were found within inspection limits."
                if result.get("truncated")
                else "No Git repositories were found under <code>/workspace</code>."
            )
            body.append(f"<p>{message}</p>")
        for repository in repositories:
            body.append("<section>")
            body.append(f"<h2><code>{escape(repository.get('path', '.'))}</code></h2>")
            if repository.get("error"):
                body.append(f'<p class="error">{escape(repository["error"])}</p>')
                body.append("</section>")
                continue
            branch = (
                "Detached HEAD"
                if repository.get("detached")
                else repository.get("branch") or "No branch"
            )
            body.append(f"<p>Branch: <code>{escape(branch)}</code></p>")
            commit = repository.get("commit")
            if commit:
                body.append(
                    f"<p>Last commit: <code>{escape(commit.get('sha', ''))}</code> "
                    f"{escape(commit.get('subject', ''))}</p>"
                )
            else:
                body.append("<p>No commits yet.</p>")
            changes = repository.get("changes", [])
            if changes:
                body.append('<table class="files"><tbody>')
                for change in changes:
                    if change.get("sensitive"):
                        label = "sensitive file omitted"
                    elif change.get("untracked"):
                        label = "untracked; contents omitted"
                    else:
                        label = change.get("status", "")
                    body.append(
                        f"<tr><td><code>{escape(label)}</code></td>"
                        f"<td><code>{escape(change.get('path', ''))}</code></td></tr>"
                    )
                body.append("</tbody></table>")
            else:
                body.append('<p class="muted">Working tree clean.</p>')
            if repository.get("truncated"):
                body.append(
                    '<p class="muted">Some file statuses were omitted by inspection limits.</p>'
                )
            for diff in repository.get("diffs", []):
                body.append(f"<h3><code>{escape(diff.get('path', ''))}</code></h3>")
                body.append(f"<pre>{escape(diff.get('text', ''))}</pre>")
            if repository.get("omitted_diffs"):
                body.append(
                    '<p class="muted">Some diffs were omitted because they were sensitive-looking, binary, large, or exceeded inspection limits.</p>'
                )
            body.append("</section>")
    body.extend([
        "<section><h2>History and recovery</h2>",
        "<p>Commits are intentional Git history. Uncommitted edits shown here are not history, and files outside Git repositories are not included. Automatic workspace history is separate; platform snapshots are recovery backups, not off-host history.</p>",
        "</section>",
        '<p class="muted">Untracked file contents are never shown. Sensitive-looking paths and common token patterns are filtered; this is not a secret scanner. Binary files and large diffs are omitted.</p>',
        "</main></body></html>",
    ])
    return HTMLResponse(
        "".join(body),
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )
