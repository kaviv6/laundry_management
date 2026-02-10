class LaundryOrder {
  const LaundryOrder({
    required this.id,
    required this.name,
    required this.customer,
    required this.status,
    required this.amountTotal,
    required this.date,
  });

  final int id;
  final String name;
  final String customer;
  final String status;
  final double amountTotal;
  final String date;

  factory LaundryOrder.fromJson(Map<String, dynamic> json) {
    return LaundryOrder(
      id: json['id'] as int,
      name: json['name'] as String? ?? '',
      customer: json['customer'] as String? ?? '',
      status: json['status'] as String? ?? 'draft',
      amountTotal: (json['amount_total'] as num?)?.toDouble() ?? 0,
      date: json['date'] as String? ?? '',
    );
  }
}
