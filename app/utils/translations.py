import os
import click
from flask.cli import AppGroup
import subprocess

translate = AppGroup('translate')

@translate.command()
@click.argument('lang')
def init(lang):
    """Initialize a new language."""
    locales_dir = os.path.join('app', 'locales')
    pot_file = os.path.join('messages.pot')

    if not os.path.exists(locales_dir):
        os.makedirs(locales_dir)

    result = subprocess.run(
        ['pybabel', 'init', '-i', pot_file, '-d', locales_dir, '-l', lang],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        click.echo(f'Initialized language: {lang}')
    else:
        click.echo(f'Error: {result.stderr}')

@translate.command()
def update():
    """Update all languages."""
    cfg_file = os.path.join('app', 'babel.cfg')
    pot_file = os.path.join('messages.pot')
    locales_dir = os.path.join('app', 'locales')

    # Extract messages
    extract_result = subprocess.run(
        ['pybabel', 'extract', '-F', cfg_file, '-k', '_', '-k', '_l', '-k', 'gettext', '-o', pot_file, '.'],
        capture_output=True,
        text=True
    )
    if extract_result.returncode != 0:
        click.echo(f'Extraction failed: {extract_result.stderr}')
        return

    click.echo('Extracted messages.')

    # Update translations
    update_result = subprocess.run(
        ['pybabel', 'update', '-i', pot_file, '-d', locales_dir],
        capture_output=True,
        text=True
    )
    if update_result.returncode == 0:
        click.echo('Updated locales.')
    else:
        click.echo(f'Update failed: {update_result.stderr}')

@translate.command()
def compile():
    """Compile translations."""
    locales_dir = os.path.join('app', 'locales')
    result = subprocess.run(
        ['pybabel', 'compile', '-d', locales_dir],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        click.echo('Compiled locales.')
    else:
        click.echo(f'Compilation failed: {result.stderr}')