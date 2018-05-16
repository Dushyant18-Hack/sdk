// Copyright (c) 2018, the Dart project authors. Please see the AUTHORS file
// for details. All rights reserved. Use of this source code is governed by a
// BSD-style license that can be found in the LICENSE file.

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:test/test.dart';

Future main() async {
  var asyncFile;
  var syncFile;

  test('Non-UTF8 Filename', () async {
    Directory.current = await Directory.systemTemp.createTemp();
    final rawPath = new Uint8List.fromList([182]);
    asyncFile = new File.fromRawPath(rawPath);

    await asyncFile.create();
    expect(await asyncFile.exists(), isTrue);
    for (final file in Directory.current.listSync()) {
      if (Platform.isWindows) {
        // Windows replaces invalid characters with � when creating file system
        // entities.
        final raw = file.rawPath;
        expect(raw.sublist(raw.length - 3), [239, 191, 189]);
      } else {
        expect(file.rawPath.last, 182);
      }
      expect(file.path.endsWith('�'), isTrue);
    }
    await asyncFile.delete();
  });

  test('Non-UTF8 Filename Sync', () {
    Directory.current = Directory.systemTemp.createTempSync();
    final rawPath = new Uint8List.fromList([182]);
    syncFile = new File.fromRawPath(rawPath);

    syncFile.createSync();
    expect(syncFile.existsSync(), isTrue);
    for (final file in Directory.current.listSync()) {
      if (Platform.isWindows) {
        // Windows replaces invalid characters with � when creating file system
        // entities.
        final raw = file.rawPath;
        expect(raw.sublist(raw.length - 3), [239, 191, 189]);
      } else {
        expect(file.rawPath.last, 182);
      }
      expect(file.path.endsWith('�'), isTrue);
    }
    syncFile.deleteSync();
  });

  tearDown(() {
    if ((asyncFile != null) && asyncFile.existsSync()) {
      asyncFile.deleteSync();
    }
    if ((syncFile != null) && syncFile.existsSync()) {
      syncFile.deleteSync();
    }
  });
}
