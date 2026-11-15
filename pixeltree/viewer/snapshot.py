"""Headless screenshots + console-error check. Uses headless chromium only; no visible browser is opened."""

from __future__ import annotations

import os


def snapshot(site: str, out: str, pages: list[str], width: int = 1440, height: int = 900,
             log=print) -> int:
    """Take a full-page screenshot of each given page of the site. Returns the total error count (the caller should exit with code 1 when it is > 0)."""
    from playwright.sync_api import sync_playwright  # imported inside the function so the core library does not depend on playwright

    os.makedirs(out, exist_ok=True)
    errors_total = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for rel in pages:
                page = browser.new_page(viewport={"width": width, "height": height})
                errs: list[str] = []
                page.on("console", lambda m, errs=errs: errs.append("console: " + m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e, errs=errs: errs.append("pageerror: %s" % e))
                path, _, frag = rel.partition("#")
                url = "file://" + os.path.abspath(os.path.join(site, path)) + ("#" + frag if frag else "")
                page.goto(url)
                page.wait_for_load_state("load")
                page.wait_for_timeout(400)
                name = path.replace("/", "_").rsplit(".", 1)[0] + ("_" + frag.replace("=", "") if frag else "") + ".png"
                dst = os.path.join(out, name)
                page.screenshot(path=dst, full_page=True)
                log("%s -> %s (%d errors)" % (rel, dst, len(errs)))
                for e in errs:
                    log("  " + e)
                errors_total += len(errs)
                page.close()
        finally:
            browser.close()
    return errors_total
