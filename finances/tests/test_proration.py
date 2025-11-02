from datetime import date
from decimal import Decimal
from django.test import TestCase
from finances.models import calculate_proration_breakdown


class ProrationBreakdownTests(TestCase):
    """Test the pure proration calculation function."""
    
    def test_single_full_month(self):
        """Full month (July 1-31) should give fraction ~1.033"""
        result = calculate_proration_breakdown(date(2024, 7, 1), date(2024, 7, 31))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["year"], 2024)
        self.assertEqual(result[0]["month"], 7)
        self.assertEqual(result[0]["days"], 31)
        self.assertEqual(result[0]["month_days"], 31)
        # 31 / 30 = 1.0333...
        self.assertEqual(result[0]["fraction"], Decimal("1.0333"))
    
    def test_partial_month_start(self):
        """Starting mid-month (July 15-31) should give fraction ~0.567"""
        result = calculate_proration_breakdown(date(2024, 7, 15), date(2024, 7, 31))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["days"], 17)  # 15-31 inclusive
        # 17 / 30 = 0.5667
        self.assertEqual(result[0]["fraction"], Decimal("0.5667"))
    
    def test_partial_month_end(self):
        """Ending mid-month (July 1-15) should give fraction 0.5"""
        result = calculate_proration_breakdown(date(2024, 7, 1), date(2024, 7, 15))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["days"], 15)
        # 15 / 30 = 0.5
        self.assertEqual(result[0]["fraction"], Decimal("0.5000"))
    
    def test_span_multiple_months(self):
        """July 15 - Sept 14 should span 3 months"""
        result = calculate_proration_breakdown(date(2024, 7, 15), date(2024, 9, 14))
        self.assertEqual(len(result), 3)
        
        # July: 15-31 = 17 days
        self.assertEqual(result[0]["month"], 7)
        self.assertEqual(result[0]["days"], 17)
        
        # August: 1-31 = 31 days
        self.assertEqual(result[1]["month"], 8)
        self.assertEqual(result[1]["days"], 31)
        
        # September: 1-14 = 14 days
        self.assertEqual(result[2]["month"], 9)
        self.assertEqual(result[2]["days"], 14)
    
    def test_year_boundary(self):
        """Dec 15, 2024 - Jan 15, 2025 should span year boundary"""
        result = calculate_proration_breakdown(date(2024, 12, 15), date(2025, 1, 15))
        self.assertEqual(len(result), 2)
        
        # December 2024
        self.assertEqual(result[0]["year"], 2024)
        self.assertEqual(result[0]["month"], 12)
        self.assertEqual(result[0]["days"], 17)  # 15-31
        
        # January 2025
        self.assertEqual(result[1]["year"], 2025)
        self.assertEqual(result[1]["month"], 1)
        self.assertEqual(result[1]["days"], 15)  # 1-15
    
    def test_leap_year_february(self):
        """Feb 2024 (leap year) should have 29 days"""
        result = calculate_proration_breakdown(date(2024, 2, 1), date(2024, 2, 29))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["days"], 29)
        self.assertEqual(result[0]["month_days"], 29)
        # 29 / 30 = 0.9667
        self.assertEqual(result[0]["fraction"], Decimal("0.9667"))
    
    def test_non_leap_year_february(self):
        """Feb 2023 (non-leap) should have 28 days"""
        result = calculate_proration_breakdown(date(2023, 2, 1), date(2023, 2, 28))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["days"], 28)
        self.assertEqual(result[0]["month_days"], 28)
        # 28 / 30 = 0.9333
        self.assertEqual(result[0]["fraction"], Decimal("0.9333"))
    
    def test_end_date_normalization(self):
        """End date on 1st should be treated as previous day (last of prev month)"""
        # May 1 should be normalized to April 30
        result = calculate_proration_breakdown(date(2024, 4, 15), date(2024, 5, 1))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["month"], 4)
        self.assertEqual(result[0]["days"], 16)  # April 15-30 (not including May 1)
    
    def test_single_day(self):
        """Single day should work"""
        result = calculate_proration_breakdown(date(2024, 7, 15), date(2024, 7, 15))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["days"], 1)
        # 1 / 30 = 0.0333
        self.assertEqual(result[0]["fraction"], Decimal("0.0333"))
    
    def test_inverted_dates(self):
        """Start after end should return empty list"""
        result = calculate_proration_breakdown(date(2024, 7, 31), date(2024, 7, 1))
        self.assertEqual(result, [])
    
    def test_full_fiscal_year(self):
        """July 1, 2024 - June 30, 2025 should span 12 months"""
        result = calculate_proration_breakdown(date(2024, 7, 1), date(2025, 6, 30))
        self.assertEqual(len(result), 12)
        
        # Total should be roughly a full year worth (365 days / 30 days per "month")
        total_fraction = sum(r["fraction"] for r in result)
        self.assertGreater(float(total_fraction), 12.0)  # More than 12 "accounting months"
        self.assertLess(float(total_fraction), 12.5)     # But not crazy high