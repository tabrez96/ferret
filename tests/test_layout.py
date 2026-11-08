from ferret.web.templating import templates


def render(**context: str) -> str:
    return templates.env.get_template("base.html").render(**context)


def test_skip_link_targets_main():
    html = render(active_nav="spending")
    skip = '<a class="skip-link" href="#main">'
    assert skip in html
    assert html.index(skip) < html.index("<aside")
    assert '<main class="main" id="main"' in html


def test_nav_marks_current_page():
    html = render(active_nav="statements")
    assert html.count('aria-current="page"') == 1
    assert 'href="/statements" aria-current="page"' in html


def test_nav_without_active_has_no_current():
    assert "aria-current" not in render()


def test_assets_are_local():
    html = render()
    assert "/static/css/ferret.css" in html
    assert "/static/js/htmx.min.js" in html
    assert "unpkg" not in html
    assert "cdn" not in html.lower()
    assert "http://" not in html
    assert "https://" not in html


def test_lang_and_color_scheme():
    html = render()
    assert '<html lang="en">' in html
    assert 'name="color-scheme" content="light dark"' in html
