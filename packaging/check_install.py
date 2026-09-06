"""Validate an image wheel against an existing host environment before mutation."""

import hashlib
import sys
from email.parser import BytesParser
from importlib import metadata
from pathlib import Path
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

wheel = Path(sys.argv[1])
with ZipFile(wheel) as archive:
    entries = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
    if len(entries) != 1:
        raise SystemExit('Image wheel must have exactly one distribution metadata record')
    product = BytesParser().parsebytes(archive.read(entries[0]))
if canonicalize_name(product['Name']) != 'paperbench-harbor':
    raise SystemExit('Image wheel is not PaperSmith')
if not SpecifierSet(product.get('Requires-Python', '')).contains('.'.join(map(str, sys.version_info[:3]))):
    raise SystemExit('Host Python does not satisfy the image wheel')
for value in product.get_all('Requires-Dist', []):
    requirement = Requirement(value)
    if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
        continue
    if requirement.url:
        raise SystemExit(f'Cannot verify direct URL dependency: {requirement.name}')
    try:
        installed = metadata.version(requirement.name)
    except metadata.PackageNotFoundError:
        raise SystemExit(f'Missing host dependency: {requirement.name}') from None
    if not requirement.specifier.contains(installed, prereleases=True):
        raise SystemExit(f'Incompatible host dependency: {requirement.name}=={installed}')
print('Selected source: image wheel')
print('Wheel SHA256:', hashlib.sha256(wheel.read_bytes()).hexdigest())
identity = '\n'.join(sorted(
    f'{canonicalize_name(d.metadata["Name"])}=={d.version}'
    for d in metadata.distributions()
    if canonicalize_name(d.metadata['Name']) != 'paperbench-harbor'
))
print('Dependency identity SHA256:', hashlib.sha256(identity.encode()).hexdigest())
