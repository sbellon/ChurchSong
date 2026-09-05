# SPDX-FileCopyrightText: 2026 Stefan Bellon
#
# SPDX-License-Identifier: MIT

class XlsxWriterException(Exception): ...  # noqa: N818 (name of the library)
class XlsxFileError(XlsxWriterException): ...
class FileCreateError(XlsxFileError): ...
