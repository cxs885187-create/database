def test_markdown_and_backlinks_escape_scripts():
    from app.markdown import render_note
    html = render_note('**Notes** <script>alert(1)</script> [[alpha]] [bad](javascript:alert(1))',{'alpha':7})
    assert '<strong>Notes</strong>' in html
    assert '<script>' not in html
    assert 'href="javascript:' not in html
    assert 'href="/words/7"' in html

def test_code_blocks_are_not_transformed_into_links():
    from app.markdown import render_note
    html = render_note('`[[alpha]]` and [[missing]]',{'alpha':7})
    assert '<code>[[alpha]]</code>' in html
    assert '<a' not in html
