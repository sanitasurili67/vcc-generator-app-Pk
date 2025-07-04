import random

def luhn_calculate(card_prefix):
    """ একটি কার্ড প্রিফিক্স থেকে Luhn অ্যালগরিদম অনুযায়ী শেষ ডিজিটটি গণনা করে """
    digits = [int(d) for d in str(card_prefix)]
    checksum = 0
    # ডান থেকে বামে, প্রতি দ্বিতীয় ডিজিটকে ২ দিয়ে গুণ করা
    for i, digit in enumerate(reversed(digits)):
        if (i % 2) == 1:
            doubled = digit * 2
            if doubled > 9:
                checksum += (doubled // 10) + (doubled % 10)
            else:
                checksum += doubled
        else:
            checksum += digit
            
    check_digit = (10 - (checksum % 10)) % 10
    return check_digit

# --- টেস্টিং শুরু ---
print("Luhn Algorithm Test starting...")

bin_to_test = "453590" 
print(f"Testing with BIN: {bin_to_test}\n")

for i in range(5):
    card_prefix = bin_to_test + ''.join(str(random.randint(0, 9)) for _ in range(15 - len(bin_to_test)))
    check_digit = luhn_calculate(card_prefix)
    final_card_num = card_prefix + str(check_digit)
    print(f"Generated Card #{i+1}: {final_card_num}")

print("\nTest finished.")