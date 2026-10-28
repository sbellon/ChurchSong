# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

import ast
import pathlib

import churchsong.churchtools
from tests.conftest import OPENAPI_ENDPOINTS, endpoint_template

# Endpoints `ChurchToolsAPI` only writes to, so there is no answer to check.
WRITE_ONLY_ENDPOINTS = {
    '/files/{}',  # DELETE of an outdated song sheet
    '/files/service/{}',  # POST of the new song sheets
}


def churchtools_api_urls() -> set[str]:
    tree = ast.parse(pathlib.Path(churchsong.churchtools.__file__).read_text('utf-8'))
    # An f-string is taken as a whole, its parts are no URLs of their own.
    f_string_parts = {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in node.values
    }
    urls = set[str]()
    for node in ast.walk(tree):
        match node:
            case ast.Constant(value=str() as url) if id(node) not in f_string_parts:
                pass
            case ast.JoinedStr(values=parts):
                url = ''.join(
                    part.value
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                    else '{}'
                    for part in parts
                )
            case _:
                continue
        if url.startswith('/api/'):
            urls.add(endpoint_template(url.removeprefix('/api')))
    return urls


# The conftest fixture `churchtools_answers_are_checked_against_openapi` fails a test
# that is answered from an endpoint the script does not list, but cannot see an
# endpoint that no test asks. So the URLs are also compared to the source, where an
# endpoint shows up even without a test, and where one that is gone has disappeared.
def test_check_openapi_lists_every_churchtools_endpoint() -> None:
    listed = {endpoint_template(path) for path in OPENAPI_ENDPOINTS}
    in_source = churchtools_api_urls()
    assert in_source - WRITE_ONLY_ENDPOINTS == listed
