import Image from 'next/image';

function BrandIcon({ src, alt, className = 'w-7 h-7' }: { src: string; alt: string; className?: string }) {
  return (
    <span className={`inline-flex items-center justify-center w-9 h-9 rounded-lg bg-white shrink-0 ${className}`}>
      <Image src={src} alt={alt} width={22} height={22} className="object-contain" />
    </span>
  );
}

export function PayPalIcon() {
  return <BrandIcon src="/images/pay/paypal.svg" alt="PayPal" />;
}
export function BinanceIcon() {
  return <BrandIcon src="/images/pay/binance.svg" alt="Binance" />;
}
export function BitcoinIcon() {
  return <BrandIcon src="/images/pay/bitcoin.svg" alt="Bitcoin" />;
}
export function EthereumIcon() {
  return <BrandIcon src="/images/pay/ethereum.svg" alt="Ethereum" />;
}
export function UsdtIcon() {
  return <BrandIcon src="/images/pay/tether.svg" alt="USDT" />;
}
