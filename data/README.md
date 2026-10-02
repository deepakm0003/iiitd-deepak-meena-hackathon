# data/

| Folder | Committed? | Contents |
|---|---|---|
| `raw/` | No (git-ignored) | Third-party downloads, e.g. the Kaggle transactions dataset |
| `replay/` | Yes (small) | Captured real items used by lite mode and the demo (added in Part 1) |
| `gold/` | Yes | Hand-labelled evaluation set and labelling guide (Part 3) |
| top level | Yes (small) | Derived aggregates such as merchant features and the synthetic book (Part 5) |

To fetch the Kaggle dataset yourself (needs a Kaggle account and API token):

```bash
kaggle datasets download computingvictor/transactions-fraud-datasets -p data/raw/kaggle_transactions --unzip
```

Lite mode does not need it: the derived files used by the demo are committed.
