import dataclasses
import json
import logging
import os
import subprocess
import sys
import typing as t

import click
import requests

# @template:logger
if 'PYCHARM_HOSTED' in os.environ:
    # must before import logzero
    os.environ['LOGZERO_FORCE_COLOR'] = '1'

import logzero  # pylint: disable=wrong-import-order,wrong-import-position

logger: logging.Logger = logzero.logger  # pylint: disable=invalid-name


# -----------------------------------------------------------------------------
# misc

class QiitaException(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        logger.error(msg)


# -----------------------------------------------------------------------------
# cli

@click.command()
# pylint: disable=bad-whitespace
# @formatter:off
# XXX: can't --verbose=2, must --verbose --verbose
@click.option(      '--dry-run',       is_flag=True,                                              help='Dry run (not implemented).')
@click.option(      '--qiita-token',   default=lambda: os.environ.get('QIITA_TOKEN', ''),         help='Qiita API access token')
@click.option('-q', '--quiet',         is_flag=True,                                              help='Quiet mode.')
@click.option('-v', '--verbose',       count=True,                                                help='Print verbose output. -vv to show debug output.')
# pylint: enable=bad-whitespace
# @formatter:on
@click.argument('path-markdown')
@click.pass_context
def cli(ctx: click.Context,
        dry_run: bool, qiita_token: str, quiet: bool, verbose: int,
        path_markdown: str):
    """TODO"""
    ctx.ensure_object(dict)
    ctx.obj['dry_run'] = dry_run

    if qiita_token == '':
        msg = '--qiita-token or environment variable QIITA_TOKEN is not set.'
        raise click.UsageError(msg, ctx=ctx)

    # @template:verbose
    if quiet and verbose:
        msg = '--quiet and --verbose are mutually exclusive.'
        raise click.UsageError(msg, ctx=ctx)
    if quiet:
        logzero.loglevel(logging.ERROR)
    elif verbose == 0:
        logzero.loglevel(logging.WARNING)
    elif verbose == 1:
        logzero.loglevel(logging.INFO)
    elif verbose >= 2:
        logzero.loglevel(logging.DEBUG)

    sys.exit(run(token=qiita_token, path_markdown=path_markdown))


def run(token: str, path_markdown: str) -> int:
    with open(path_markdown) as f:
        md = f.read()
    header = parse_header(md)
    if header.url is None:
        return post(token=token, header=header, md=md)
    else:
        return patch(token=token, header=header, md=md)


# -----------------------------------------------------------------------------
# header

@dataclasses.dataclass(frozen=False)
class ArticleHeader:
    title: t.Optional[str] = None
    url: t.Optional[str] = None
    tags: t.List[str] = dataclasses.field(default_factory=list)

    # allow no argument
    def __init__(self):
        pass


def parse_header(md: str) -> ArticleHeader:
    fst = md[:md.find('\n')]
    if fst != '<!--':
        raise QiitaException(f'line 1: not <!-- ; was: {fst}')
    del fst

    header = ArticleHeader()
    i = 2
    title, url, tags = '', '', []
    for line in md[md.find('\n') + 1:].split('\n'):
        logger.debug(f'{i}: {line}')
        if line == '-->':
            return header
        key, value = (x.strip() for x in line.split(':', 1))
        parse_kv(line=i, key=key, value=value, header=header)
        i += 1

    raise QiitaException('--> not found')


def parse_kv(line: int, key: str, value: str, header: ArticleHeader) -> None:
    # Python 3.8
    # tmp: t.Dict[str, t.Callable[[ArticleHeader], None]]  = {
    #     '0file': (lambda x: (x.title := value)),
    # }
    if key == '0file':
        return
    elif key == '0title':
        header.title = value
    elif key == '0url':
        if 'TODO' in value:
            logger.debug('skip TODO')
            return
        header.url = value
    elif key == 'tags':
        header.tags = [x.strip() for x in value.split(' ')]
    else:
        logger.warning(f'line {line}: skip: {key}: {value}')


# -----------------------------------------------------------------------------
# API

def confirm(header: ArticleHeader, md: str, method: str) -> bool:
    logger.info(f'title:   {header.title}')
    logger.info(f'url:     {header.url}')
    logger.info(f'tags:    {header.tags}')
    logger.info('content: {}'.format(md[:50].replace('\n', ' ')))
    logger.info('         ... {}'.format(md[-50:].replace('\n', ' ')))
    logger.info(f'#{method}? [y/N]')
    tmp = input().strip()
    if tmp.lower() not in ['y', 'yes']:
        logger.warning('abort')
        return False
    return True


def post(token: str, header: ArticleHeader, md: str) -> int:
    """https://qiita.com/api/v2/docs#post-apiv2items"""

    headers = {
        # 'content-type': 'application/json',  # TODO: remove me
        # 'charset': 'utf-8',  # TODO: remove me
        'Authorization': f'Bearer {token}'
    }
    tags = [{'name': x, 'versions': []} for x in header.tags]
    jsn = {
        'body': md,
        'tags': tags,
        'title': header.title,
    }
    if not confirm(header=header, md=md, method='POST'):
        return 1
    resp = requests.post('https://qiita.com/api/v2/items', json=jsn,
                         headers=headers)
    resp.raise_for_status()
    jsn = resp.json()
    print(f'0url: {jsn["url"]}')
    return 0


def patch(token: str, header: ArticleHeader, md: str) -> int:
    """https://qiita.com/api/v2/docs#patch-apiv2itemsitem_id"""

    headers = {
        'Authorization': f'Bearer {token}'
    }
    tags = [{'name': x, 'versions': []} for x in header.tags]
    jsn = {
        'body': md,
        'tags': tags,
        'title': header.title,
    }
    item = header.url[header.url.rfind('/') + 1:]

    resp = requests.get(f'https://qiita.com/api/v2/items/{item}',
                        headers=headers)
    resp.raise_for_status()
    resp_json = resp.json()
    with open('/tmp/qiita.py.md.remote', 'w') as f:
        f.write(resp_json['body'])
    with open('/tmp/qiita.py.md.local', 'w') as f:
        f.write(md)
    logger.info('icdiff /tmp/qiita.py.md.remote /tmp/qiita.py.md.local')
    subprocess.run('icdiff /tmp/qiita.py.md.remote /tmp/qiita.py.md.local',
                   shell=True)
    resp_json['body']

    if not confirm(header=header, md=md, method='PATCH'):
        return 1
    resp = requests.patch(f'https://qiita.com/api/v2/items/{item}', json=jsn,
                          headers=headers)
    resp.raise_for_status()
    resp_json = resp.json()
    print(f'0url: {resp_json["url"]}')
    return 0


# -----------------------------------------------------------------------------

if __name__ == '__main__':
    cli()
