"""How astra-tools works its answers out. Nothing here is public: another package imports
`astra.api`.

In layers, each of which imports only from itself, the ones before it, and the data model and
errors (`astra.model`, `astra.errors`):

- `sources`: where every byte comes from, a working tree or a commit, and the cache;
- `documents`: a file as a document, parsed and checked by its schema, and the rule catalogue;
- `analysis`: the analyses bound into a stack and what they mean: universes, the validator's
  rules, `validate` and `resolve`;
- `results`: the records of an analysis's results: read, written, hashed and checked, and
  their history in git.

`papers`, beside them, is the paper cache and the quotes sought in it.
"""
