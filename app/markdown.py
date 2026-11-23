"""Markdown rendering with raw HTML disabled and safely resolved Wiki links."""
from html import escape
from markdown_it import MarkdownIt

def wiki_link(state,silent):
    if not state.src.startswith('[[',state.pos):
        return False
    end = state.src.find(']]',state.pos+2)
    if end<0:
        return False
    text = state.src[state.pos+2:end].strip()
    if not text or '\n' in text:
        return False
    if not silent:
        token = state.push('wiki_link','',0)
        token.content = text
    state.pos = end+2
    return True

def render_note(body,links):
    parser = MarkdownIt('commonmark',{'html':False})
    parser.inline.ruler.before('link','wiki_link',wiki_link)
    def render(tokens,index,options,env):
        text = tokens[index].content
        target = links.get(text.lower())
        return f'<a href="/words/{int(target)}">{escape(text)}</a>' if target else escape(text)
    parser.renderer.rules['wiki_link'] = render
    return parser.render(body)
