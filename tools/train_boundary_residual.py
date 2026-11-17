"""Research-only character CNN that learns residuals over frozen Kiwi boundaries.

Training/reference text stays in caller-selected local build files. Checkpoints
are experimental derivatives, not automatically bundled or publicly released.
All references are fixed before training; no sentence text is printed.
"""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MAX_LEN = 160
VOCAB = 11820


def encode_char(char):
    value = ord(char)
    if 0xAC00 <= value <= 0xD7A3:
        return value - 0xAC00 + 1
    if value < 128:
        return 11173 + value
    return 11301 + value % 512


def text_parts(text):
    raw, cuts = [], []
    boundary = False
    for char in text.strip():
        if char == ' ':
            boundary = True
        else:
            raw.append(char)
            cuts.append(int(boundary and len(raw) > 1))
            boundary = False
    return ''.join(raw), cuts


def prepare(args):
    from compare_spacing import engine_fingerprint
    fingerprint = engine_fingerprint(args.engine)
    sys.path.insert(0, str(Path(args.engine).resolve()))
    from hangul_ime.release_spacing import KiwiSpacer
    kwargs = {'refiner_path': False} if 'refiner_path' in inspect.signature(KiwiSpacer).parameters else {}
    spacer = KiwiSpacer(**kwargs)
    names, rows, seen, duplicates, lengths = [], [], set(), 0, []
    for value in args.corpus:
        name, filename = value.split('=', 1)
        contents = Path(filename).read_bytes()
        names.append({'name': name, 'sha256': hashlib.sha256(contents).hexdigest()})
        for text in contents.decode('utf-8-sig').splitlines():
            raw, gold = text_parts(text)
            if not 2 <= len(raw) <= MAX_LEN or '\t' in raw:
                continue
            key = hashlib.sha256(raw.encode()).digest()
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            rows.append((raw, gold, len(names) - 1))
    if not rows:
        raise ValueError('no eligible rows')
    ids = np.zeros((len(rows), MAX_LEN), dtype=np.uint16)
    golds = np.zeros(ids.shape, dtype=np.uint8)
    bases = np.zeros(ids.shape, dtype=np.uint8)
    groups = np.zeros(len(rows), dtype=np.uint8)
    start = time.monotonic()
    for i, (raw, gold, group) in enumerate(rows):
        output = spacer.space(raw)
        got, base = text_parts(output)
        if got != raw:
            raise ValueError('baseline changed characters')
        length = len(raw)
        ids[i, :length] = [encode_char(c) for c in raw]
        golds[i, :length], bases[i, :length] = gold, base
        groups[i] = group
        lengths.append(length)
        if (i + 1) % 5000 == 0:
            print(json.dumps({'prepared': i + 1, 'total': len(rows),
                              'elapsed_s': round(time.monotonic() - start, 1)}), flush=True)
    output = Path(args.output)
    if engine_fingerprint(args.engine) != fingerprint:
        raise ValueError('baseline engine changed during preparation')
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, ids=ids, gold=golds, baseline=bases,
                        groups=groups, lengths=np.array(lengths, dtype=np.uint16))
    meta = {'sources': names, 'rows': len(rows), 'duplicates_removed': duplicates,
            'baseline_engine_sha256': fingerprint,
            'max_length': MAX_LEN, 'raw_utf8_text_included': False, 'tokenized_text_retained': True,
            'purpose': 'local research; not a public redistribution artifact'}
    output.with_suffix('.json').write_text(json.dumps(meta, indent=2) + '\n', encoding="utf-8")
    print(json.dumps(meta), flush=True)


def make_model():
    import torch
    from torch import nn

    class ResidualCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.chars = nn.Embedding(VOCAB, 32, padding_idx=0)
            self.boundaries = nn.Embedding(2, 4)
            self.encoder = nn.Sequential(
                nn.Conv1d(36, 64, 5, padding=2), nn.ReLU(),
                nn.Conv1d(64, 64, 5, padding=4, dilation=2), nn.ReLU(),
                nn.Conv1d(64, 48, 5, padding=8, dilation=4), nn.ReLU(),
                nn.Conv1d(48, 1, 1),
            )
            nn.init.zeros_(self.encoder[-1].weight)
            nn.init.zeros_(self.encoder[-1].bias)

        def forward(self, ids, base):
            features = torch.cat((self.chars(ids), self.boundaries(base)), -1)
            delta = self.encoder(features.transpose(1, 2)).squeeze(1)
            return (base.float() * 2 - 1) * 4 + delta

    return ResidualCNN()


def metrics(gold, predicted, mask, base):
    def one(p):
        tp = int(np.sum(p & gold & mask))
        fp = int(np.sum(p & ~gold & mask))
        fn = int(np.sum(~p & gold & mask))
        exact = int(np.sum(np.all((p == gold) | ~mask, axis=1)))
        return {'count': len(gold), 'exact': exact, 'tp': tp, 'fp': fp, 'fn': fn,
                'f1': 2 * tp / max(1, 2 * tp + fp + fn)}
    return {'baseline': one(base), 'candidate': one(predicted)}


def train(args):
    import torch
    import torch.nn.functional as F
    torch.manual_seed(20261002)
    np.random.seed(20261002)
    torch.set_num_threads(2)
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    data, dev = np.load(args.train), np.load(args.dev)
    model = make_model().to(device)
    first_epoch = 0
    if args.resume:
        checkpoint = torch.load(args.resume, map_location='cpu', weights_only=True)
        model.load_state_dict(checkpoint['state_dict'])
        first_epoch = checkpoint['epoch']
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0001)
    ids = torch.tensor(data['ids'].astype(np.int64), device=device)
    base = torch.tensor(data['baseline'].astype(np.int64), device=device)
    gold = torch.tensor(data['gold'].astype(np.float32), device=device)
    mask = ids != 0
    mask[:, 0] = False
    dev_ids = torch.tensor(dev['ids'].astype(np.int64), device=device)
    dev_base = torch.tensor(dev['baseline'].astype(np.int64), device=device)
    dev_gold, dev_baseline = dev['gold'].astype(bool), dev['baseline'].astype(bool)
    dev_mask = dev['ids'] != 0
    dev_mask[:, 0] = False
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    records = []
    widths = np.minimum(MAX_LEN, ((data['lengths'].astype(np.int32) + 29) // 16) * 16)
    rng = np.random.default_rng(20261002)
    for epoch in range(first_epoch, first_epoch + args.epochs):
        started = time.monotonic()
        model.train()
        schedule = []
        for width in sorted(set(widths)):
            order = rng.permutation(np.flatnonzero(widths == width))
            schedule.extend((int(width), order[start:start + args.batch])
                            for start in range(0, len(order), args.batch))
        rng.shuffle(schedule)
        total_loss = 0.
        batches = 0
        for width, indices in schedule:
            ix = torch.as_tensor(indices, device=device)
            optimizer.zero_grad(set_to_none=True)
            active = mask[ix, :width]
            logits = model(ids[ix, :width], base[ix, :width])
            loss = F.binary_cross_entropy_with_logits(logits[active], gold[ix, :width][active])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += loss.item()
            batches += 1
            if batches % 100 == 0:
                print(json.dumps({'epoch': epoch + 1, 'batches': batches,
                                  'loss': total_loss / batches}), flush=True)
        model.eval()
        values = []
        with torch.no_grad():
            for start in range(0, len(dev_ids), args.batch):
                values.append(model(dev_ids[start:start + args.batch],
                                    dev_base[start:start + args.batch]).cpu().numpy())
        logits = np.concatenate(values)
        report = {'epoch': epoch + 1, 'loss': total_loss / batches,
                  'elapsed_s': round(time.monotonic() - started, 2), 'thresholds': {}}
        for threshold in [0., 1., 2., 3., 4., 5., 6., 8.]:
            selected = np.where(np.abs(logits) >= threshold, logits > 0, dev_baseline)
            grouped = {}
            for group in sorted(set(dev['groups'])):
                ix = dev['groups'] == group
                grouped[str(group)] = metrics(dev_gold[ix], selected[ix], dev_mask[ix], dev_baseline[ix])
            report['thresholds'][str(threshold)] = grouped
        records.append(report)
        torch.save({'state_dict': {k: v.cpu() for k, v in model.state_dict().items()},
                    'vocab': VOCAB, 'max_length': MAX_LEN, 'epoch': epoch + 1,
                    'architecture': 'char32-boundary4-dilated-conv64-64-48',
                    'batching': 'length buckets with 14 characters of right context, maximum 160',
                    'seed': 20261002, 'learning_rate': args.lr, 'batch_size': args.batch,
                    'trainer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'training_cache_sha256': hashlib.sha256(Path(args.train).read_bytes()).hexdigest(),
                    'development_cache_sha256': hashlib.sha256(Path(args.dev).read_bytes()).hexdigest(),
                    'purpose': 'restricted local research; source permissions required for public release'},
                   output / f'epoch-{epoch + 1}.pt')
        (output / 'training.json').write_text(json.dumps(records, indent=2) + '\n', encoding="utf-8")
        np.savez_compressed(output / f'dev-logits-{epoch + 1}.npz', logits=logits)
        compact = {k: {g: (v['baseline']['exact'], v['candidate']['exact'],
                           round(v['candidate']['f1'], 6)) for g, v in val.items()}
                   for k, val in report['thresholds'].items()}
        print(json.dumps({'epoch': epoch + 1, 'elapsed_s': report['elapsed_s'],
                          'dev': compact}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    p.add_argument('--engine', required=True)
    p.add_argument('--corpus', action='append', required=True)
    p.add_argument('--output', required=True)
    p = commands.add_parser('train')
    p.add_argument('--train', required=True)
    p.add_argument('--dev', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--epochs', type=int, default=4)
    p.add_argument('--batch', type=int, default=128)
    p.add_argument('--lr', type=float, default=.002)
    p.add_argument('--resume')
    args = parser.parse_args()
    (prepare if args.command == 'prepare' else train)(args)


if __name__ == '__main__':
    main()
