# embed_products.py
# Reads product_info.csv, extracts attributes from neuralens_processed_data,
# generates OpenAI embeddings, saves products_with_embeddings.json
#
# Usage:
#   export OPENAI_API_KEY="sk-..."
#   python embed_products.py
#
# Input:  product_info.csv  (1,806 products)
# Output: products_with_embeddings.json
# Cost:   ~$0.002 total for 1,806 PIDs

import json
import os
import re
import argparse
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SKIP_ATTRIBUTES = {
    'Component Count', 'Gender', 'Image Type', 'No of Component',
    'Size Details', 'Fit', 'Visible Items not included',
    'Care Instruction', 'Disclaimer', 'Component Attributes'
}

def parse_csv_line(line):
    """
    Parse one CSV line from product_info.csv.
    Cannot use standard CSV parser — neuralens_processed_data contains
    commas inside nested JSON which breaks standard parsers.

    Format: productID,productTitle,"image_urls","neuralens_json"
    """
    line = line.strip()
    if not line:
        return None

    # Extract productID (everything before first comma)
    first_comma = line.index(',')
    pid = line[:first_comma].strip()

    rest = line[first_comma + 1:]

    # Extract productTitle (may or may not be quoted)
    if rest.startswith('"'):
        title_end = rest.index('",', 1)
        title = rest[1:title_end]
        rest = rest[title_end + 2:]
    else:
        title_end = rest.index(',')
        title = rest[:title_end]
        rest = rest[title_end + 1:]

    # Extract image_urls (quoted, comma-separated URLs inside quotes)
    if rest.startswith('"'):
        # Find the closing quote before the JSON blob
        # JSON starts with ,"[{ so find that pattern
        json_marker = rest.find('","[{')
        if json_marker == -1:
            json_marker = rest.find(',"[{')
            image_str = rest[1:json_marker]
            json_raw = rest[json_marker + 2:]
        else:
            image_str = rest[1:json_marker]
            json_raw = rest[json_marker + 2:]
    else:
        comma_pos = rest.index(',"[{')
        image_str = rest[:comma_pos]
        json_raw = rest[comma_pos + 1:]

    # Clean image URLs
    images = [u.strip().strip('"') for u in image_str.split(',') if 'azafashions' in u]

    # Clean JSON — strip surrounding quotes and trailing chars
    json_raw = json_raw.strip()
    if json_raw.startswith('"'):
        json_raw = json_raw[1:]
    if json_raw.endswith('"'):
        json_raw = json_raw[:-1]

    return pid, title, images, json_raw


def extract_attributes(neuralens_raw):
    """Parse neuralens JSON and extract display-worthy attributes."""
    try:
        data = json.loads(neuralens_raw)
        global_entry = next(
            (d for d in data if d.get('key') == 'global'),
            data[0] if data else {}
        )

        result = {
            'description': global_entry.get('description', ''),
            'keywords':    global_entry.get('keywords', []),
            'attributes':  {}
        }

        for attr in global_entry.get('attributes', []):
            display_name = attr.get('display_name') or attr.get('key', '')
            if display_name in SKIP_ATTRIBUTES:
                continue
            val = attr.get('value', [])
            if not val:
                continue
            if isinstance(val, list):
                val = [str(v) for v in val if v and str(v).strip()]
            if val:
                result['attributes'][display_name] = val

        return result

    except Exception as e:
        return {'description': '', 'keywords': [], 'attributes': {}, 'error': str(e)}


def build_embedding_text(pid, title, attrs):
    """
    Build rich embedding string from all available product attributes.
    This is what gets embedded — the richer it is, the better the matching.
    """
    parts = [title]

    desc = attrs.get('description', '')
    if desc:
        parts.append(desc)

    # Add each attribute as "Key: value1, value2"
    priority_keys = [
        'Short Description', 'Occasions', 'Occasion', 'Style Genre',
        'Components', 'Noteworthy Feature', 'Fabric', 'Color', 'Pattern',
        'Type of Work', 'Pattern Style', 'Embellishment Style', 'Border Style',
        'Neckline Style', 'Sleeve Style'
    ]

    # Priority attributes first
    attrs_dict = attrs.get('attributes', {})
    for key in priority_keys:
        if key in attrs_dict:
            val = attrs_dict[key]
            parts.append(f"{key}: {', '.join(val)}")

    # Remaining attributes
    for key, val in attrs_dict.items():
        if key not in priority_keys:
            parts.append(f"{key}: {', '.join(val)}")

    # Keywords last (semantic enrichment)
    keywords = attrs.get('keywords', [])
    if keywords:
        parts.append(f"Keywords: {', '.join(keywords[:12])}")

    return '. '.join(p for p in parts if p.strip())


def embed_batch(texts):
    """Call OpenAI embeddings API for a batch of texts."""
    resp = client.embeddings.create(
        model='text-embedding-3-small',
        input=texts
    )
    return [r.embedding for r in resp.data]


def run(input_path, output_path):
    print(f"Reading {input_path}...")

    products = []
    errors   = []

    with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    # Skip header
    for i, line in enumerate(lines[1:], start=2):
        try:
            parsed = parse_csv_line(line)
            if not parsed:
                continue
            pid, title, images, json_raw = parsed
            attrs = extract_attributes(json_raw)

            if 'error' in attrs:
                errors.append(f"Line {i} PID {pid}: {attrs['error']}")
                continue

            embedding_text = build_embedding_text(pid, title, attrs)

            products.append({
                'pid':            pid,
                'title':          title,
                'images':         images,
                'description':    attrs['description'],
                'keywords':       attrs['keywords'],
                'attributes':     attrs['attributes'],
                'pdp_url':        f'https://www.samyuktasinghania.com/products/{pid}/{pid}',
                'embedding_text': embedding_text,
                'embedding':      None   # filled below
            })

        except Exception as e:
            errors.append(f"Line {i}: {e}")

    print(f"Parsed {len(products)} products ({len(errors)} errors)")
    if errors[:5]:
        print("First errors:", errors[:5])

    # Generate embeddings in batches of 100
    print(f"\nGenerating embeddings...")
    texts      = [p['embedding_text'] for p in products]
    BATCH_SIZE = 100
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        embs  = embed_batch(batch)
        all_embeddings.extend(embs)
        print(f"  {min(i + BATCH_SIZE, len(texts))}/{len(products)} done")

    for p, emb in zip(products, all_embeddings):
        p['embedding'] = emb

    with open(output_path, 'w') as f:
        json.dump(products, f)

    total_tokens = sum(len(t.split()) for t in texts)
    cost = (total_tokens / 1_000_000) * 0.02
    print(f"\nDone. Saved {len(products)} products to {output_path}")
    print(f"Estimated cost: ~${cost:.4f}")
    print(f"File size: ~{len(json.dumps(products)) // 1024 // 1024}MB")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  default='product_info.csv')
    parser.add_argument('--output', default='products_with_embeddings.json')
    args = parser.parse_args()
    run(args.input, args.output)
