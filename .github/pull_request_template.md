**What this changes, and why**

<!-- The reasoning matters more than the diff. A future reader wants to know what
     you knew that made this the right answer. -->

**Checks**

- [ ] `pytest -q` passes
- [ ] `ruff check src tests` passes
- [ ] New behaviour has a test that fails without it
- [ ] If it touches authorisation, the negative case is tested too
- [ ] If it touches the schema, the migration was run against PostgreSQL
- [ ] Documentation updated where the behaviour is described
