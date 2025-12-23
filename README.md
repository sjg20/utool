# utool - U-Boot Automation Tool

This is a a simple tool to handle common tasks when developing U-Boot.

## Usage

```bash
# Push with specific tests
./utool ci -s -p -j rpi4

# Dry-run to see what would be executed
./utool --dry-run ci -w

# Run tests
./utool test
```

## CI Options

- `-s, --test-suites`: Enable TEST_SUITES
- `-p, --test-py`: Enable TEST_PY  
- `-w, --world-build`: Enable WORLD_BUILD
- `-l, --lab-only`: Enable LAB_ONLY
- `-j, --sjg-lab ROLE`: Set SJG_LAB variable
- `-t, --test-spec SPEC`: Set TEST_SPEC variable
- `-f, --force`: Force push

## Testing

The tool includes comprehensive tests using the U-Boot test framework:

```bash
# Run all tests
./utool test

# Run specific test
./utool test test_ci_subcommand_parsing
```
