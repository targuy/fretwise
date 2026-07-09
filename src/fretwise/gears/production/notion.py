import json
import os
import time
import urllib.error
import urllib.request


class NotionError(Exception):
    pass


class NotionClient:
    def __init__(self, config, run_dir):
        self.config = config
        self.run_dir = run_dir
        self.mode = config["notion"].get("mode", "dry_run")
        self.api_version = config["notion"].get("api_version", "2026-03-11")
        self.token = os.environ.get("NOTION_API_KEY")

    def create_song_page(self, profile, payload):
        if self.mode == "dry_run":
            return self._write_dry_run(profile, payload)
        if not self.token:
            raise NotionError("NOTION_API_KEY is not set")
        page = self._create_page(payload)
        template = self.config["notion"].get("template", {})
        if template.get("enabled") and template.get("append_generated_blocks", True):
            time.sleep(float(template.get("append_delay_seconds", 2)))
            self._append_children(page["id"], payload["children"])
        elif len(payload["children"]) > 100:
            self._append_children(page["id"], payload["children"][100:])
        return page

    def _write_dry_run(self, profile, payload):
        os.makedirs(self.run_dir, exist_ok=True)
        path = os.path.join(self.run_dir, "notion_payloads.jsonl")
        record = {
            "song": profile.get("song", {}),
            "request": self._page_body(payload),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"id": "dry-run", "url": path}

    def _create_page(self, payload):
        return self._request("POST", "https://api.notion.com/v1/pages", self._page_body(payload))

    def _append_children(self, block_id, children):
        for chunk in _chunks(children, 100):
            self._request(
                "PATCH",
                f"https://api.notion.com/v1/blocks/{block_id}/children",
                {"children": chunk},
            )

    def _page_body(self, payload):
        notion = self.config["notion"]
        parent_type = notion.get("parent_type", "data_source_id")
        body = {
            "parent": {parent_type: notion["parent_id"]},
            "properties": payload["properties"],
        }
        template = notion.get("template", {})
        if template.get("enabled"):
            body["template"] = {
                "type": "template_id",
                "template_id": template["template_id"],
                "timezone": template.get("timezone", "UTC"),
            }
            if not template.get("append_generated_blocks", True):
                return body
        else:
            body["children"] = payload["children"][:100]
        return body

    def _request(self, method, url, body):
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": self.api_version,
        }
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in (429, 529, 503):
                    retry_after = exc.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else min(30, 2**attempt)
                    time.sleep(delay)
                    continue
                raise NotionError(f"Notion HTTP {exc.code}: {detail}") from exc
        raise NotionError(f"Notion request did not succeed after retries: {method} {url}")


def _chunks(items, size):
    for index in range(0, len(items), size):
        yield items[index : index + size]
