import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/laundry_order.dart';

class OdooApiService {
  OdooApiService({required this.baseUrl, http.Client? client})
      : _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  String? _sessionId;

  Map<String, String> _headers() {
    final headers = <String, String>{'Content-Type': 'application/json'};
    if (_sessionId != null) {
      headers['Cookie'] = 'session_id=$_sessionId';
    }
    return headers;
  }

  Future<Map<String, dynamic>> _jsonRpcCall({
    required String path,
    required Map<String, dynamic> params,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final body = jsonEncode({
      'jsonrpc': '2.0',
      'method': 'call',
      'params': params,
      'id': DateTime.now().millisecondsSinceEpoch,
    });

    final response = await _client.post(uri, headers: _headers(), body: body);
    if (response.statusCode != 200) {
      throw Exception('HTTP ${response.statusCode}: ${response.body}');
    }

    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    if (decoded['error'] != null) {
      throw Exception(decoded['error'].toString());
    }

    return decoded['result'] as Map<String, dynamic>;
  }

  Future<void> login({
    required String db,
    required String username,
    required String password,
  }) async {
    final result = await _jsonRpcCall(
      path: '/api/login',
      params: {'db': db, 'username': username, 'password': password},
    );

    if (result['status'] != true) {
      throw Exception(result['error']?.toString() ?? 'Login failed');
    }

    _sessionId = result['session_id']?.toString();
    if (_sessionId == null || _sessionId!.isEmpty) {
      throw Exception('Missing session id from login response');
    }
  }

  Future<List<LaundryOrder>> fetchOrders() async {
    final result = await _jsonRpcCall(path: '/api/laundry/orders', params: {});
    if (result['status'] != true) {
      throw Exception(result['error']?.toString() ?? 'Could not fetch orders');
    }

    final orders = (result['orders'] as List<dynamic>? ?? [])
        .cast<Map<String, dynamic>>()
        .map(LaundryOrder.fromJson)
        .toList();
    return orders;
  }
}
