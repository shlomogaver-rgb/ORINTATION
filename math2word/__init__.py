"""math2word: Hebrew math exam PDF/image -> editable Word document (RTL text, native equations, figures)."""
from .docx_builder import Builder, Options
from .source import load_pages

__all__ = ["Builder", "Options", "load_pages", "convert"]


def convert(input_path, output_path, pages=None, cache_dir=".math2word_cache", all_pages=False,
            options=None, model=None, effort="high", workers=4, progress=print):
    """Full pipeline: load -> transcribe each page with Claude -> build DOCX."""
    from concurrent.futures import ThreadPoolExecutor

    import anthropic

    from .transcribe import MODEL, transcribe_page

    page_objs = load_pages(input_path, pages=pages)
    client = anthropic.Anthropic()
    total = len(page_objs)

    def work(po):
        result = transcribe_page(client, po, total, cache_dir=cache_dir, model=model or MODEL, effort=effort)
        progress(f"  page {po.index + 1}: {result.get('page_type')} "
                 f"({len(result.get('blocks', []))} blocks, {len(result.get('figures', []))} figures)")
        return result

    progress(f"transcribing {total} page(s)…")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        pages_json = list(ex.map(work, page_objs))

    include = ("questions", "instructions", "formula_sheet", "other")
    if all_pages:
        include += ("cover", "answer_space", "blank")
    Builder(options).build(pages_json, page_objs, output_path, include_types=include)
    progress(f"saved {output_path}")
    return pages_json
