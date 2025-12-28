- Commit messages should use present imperative, first describing any problem or motivation in its own paragraph, then what the patch does. The current source is how things are now, not how they were

## Coding style

- Keep identifiers short. If there's only one 'part' in a function, call it `part`, not `allocated_part`
- Prefer short function names: `exec_cmd` not `run_or_show_command`, `build_desc` not `append_tags_to_description`
- Avoid `getattr(args, 'foo', default)` when the attribute is guaranteed to exist; use `args.foo` directly

## Testing

- Run tests with: `PYTHONPATH=~/u/tools python -m pytest uman_pkg/ftest.py -v`
- Run pylint with: `PYTHONPATH=~/u/tools python3 -m pylint uman_pkg/ftest.py`

### Test conventions

- Use `terminal.capture() as (out, err)` for tuple unpacking, not `as out`
- Keep capture blocks minimal - only wrap the code that produces output
- Put expected value first in asserts: `self.assertEqual(expected, actual)`
- Use `assertFalse(out.getvalue())` for checking empty output, not `assertEqual('', ...)`
- Check both stdout and stderr in all captures
- Check full output strings, not partial matches with assertIn
- Use `orig_` prefix for saved values, not `original_`
- Use `command.TEST_RESULT` for mocking command execution, restore in tearDown
- Put `tout.init()` in setUp(), not inside individual tests
- Put assertRaises outside terminal.capture so test failures show output
- Use `cmdline.parse_args(['cmd', 'arg'])` in tests instead of `argparse.Namespace(...)`
