// SPDX-License-Identifier: GPL-3.0
/*
    Copyright 2021 0KIMS association.

    This file is generated with [snarkJS](https://github.com/iden3/snarkjs).

    snarkJS is a free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    snarkJS is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
    or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
    License for more details.

    You should have received a copy of the GNU General Public License
    along with snarkJS. If not, see <https://www.gnu.org/licenses/>.
*/

pragma solidity >=0.7.0 <0.9.0;

contract Phase7Groth16Verifier {
    // Scalar field size
    uint256 constant r    = 21888242871839275222246405745257275088548364400416034343698204186575808495617;
    // Base field size
    uint256 constant q   = 21888242871839275222246405745257275088696311157297823662689037894645226208583;

    // Verification Key data
    uint256 constant alphax  = 12663724529090689766797911430690550956033044315126929996625611822911997733473;
    uint256 constant alphay  = 21573452390329068143699214881274096085312511388104098153212223615053306144399;
    uint256 constant betax1  = 17616577217414677648381724392616672599516152665782412540673792137116034634727;
    uint256 constant betax2  = 1812322857048398442287360364385556750089343681438299990600275208371214207917;
    uint256 constant betay1  = 8651462747976650531523692889319570195580419537133214502608575365974423468593;
    uint256 constant betay2  = 3906960677383510145185076851917114008908874219703691295803726472477202904000;
    uint256 constant gammax1 = 11559732032986387107991004021392285783925812861821192530917403151452391805634;
    uint256 constant gammax2 = 10857046999023057135944570762232829481370756359578518086990519993285655852781;
    uint256 constant gammay1 = 4082367875863433681332203403145435568316851327593401208105741076214120093531;
    uint256 constant gammay2 = 8495653923123431417604973247489272438418190587263600148770280649306958101930;
    uint256 constant deltax1 = 10273742377691786894740050638047300895887937479740698937123015496689456810640;
    uint256 constant deltax2 = 6410261179240854535937338831709927534480525568985966037752690256289433868779;
    uint256 constant deltay1 = 10585348484128856759933529449010316540592771148258759408253537508199177652487;
    uint256 constant deltay2 = 904442530073982954699654226014870771192519648158038916425386044292214390637;

    
    uint256 constant IC0x = 7927808942906890442432721810694683766372718563449155233774019988419672629519;
    uint256 constant IC0y = 5583646968394616011187066265838510339129917728847472195067585347649176678155;
    
    uint256 constant IC1x = 14508408828014390658830457769289052722237354808796900229680381884319921327759;
    uint256 constant IC1y = 1663041346057674954923884690077801587567203722770064637685458256464639349159;
    
    uint256 constant IC2x = 19529028417301954034383044468661990865659811976283845814919506779605619584523;
    uint256 constant IC2y = 16824845646874199397873207889735066608434477514413553722555712447006970166360;
    
    uint256 constant IC3x = 19233156429356346516035147240512967895311016919380916489639192200555761481621;
    uint256 constant IC3y = 3408845583826617527984058888810750808661409570798717691963989215240375630703;
    
    uint256 constant IC4x = 21375947964849143418471042918909068149592715117269533248338922362536763639818;
    uint256 constant IC4y = 2893816893886472120102956992924532319071010559432793729860182459919207094421;
    
    uint256 constant IC5x = 11590541695014659031421093839984712329678914153839123473760839889642807561204;
    uint256 constant IC5y = 5328721077816075667670333144810272257930716821835140489679389946201791638121;
    
    uint256 constant IC6x = 17272835134608642041791245995500524886893554318193118771273475892662547018840;
    uint256 constant IC6y = 9822358710233339875375626421535475453199654760970702869087653507962949635394;
    
    uint256 constant IC7x = 9473562538655159370572504239038506409577935004535030916523785130439866181622;
    uint256 constant IC7y = 21583255478447085904886810840193437737860255228516814128634533497196947568560;
    
    uint256 constant IC8x = 8803858689443064578795068263895871516337967095063106140715646403663023909323;
    uint256 constant IC8y = 3403644623680398138869806564208711496916395750406272573595481131820354301103;
    
    uint256 constant IC9x = 18752466982026461605912427281338636714336922128291459847117189958434073734442;
    uint256 constant IC9y = 7053984609824001639928961778735924589837020439557168704852945978169486816062;
    
    uint256 constant IC10x = 4623439770816203596197847594306750724571770312907001282273377627657376077994;
    uint256 constant IC10y = 8837372044039926823621136934030760381780111370969315310461946941336027033878;
    
    uint256 constant IC11x = 290675184090728535776355085626053589743703732580502924206769210732685791022;
    uint256 constant IC11y = 4725808619908809704452763953737413721221391739878385676355470104152223189417;
    
 
    // Memory data
    uint16 constant pVk = 0;
    uint16 constant pPairing = 128;

    uint16 constant pLastMem = 896;

    function verifyProof(uint[2] calldata _pA, uint[2][2] calldata _pB, uint[2] calldata _pC, uint[11] calldata _pubSignals) public view returns (bool) {
        assembly {
            function checkField(v) {
                if iszero(lt(v, r)) {
                    mstore(0, 0)
                    return(0, 0x20)
                }
            }
            
            // G1 function to multiply a G1 value(x,y) to value in an address
            function g1_mulAccC(pR, x, y, s) {
                let success
                let mIn := mload(0x40)
                mstore(mIn, x)
                mstore(add(mIn, 32), y)
                mstore(add(mIn, 64), s)

                success := staticcall(sub(gas(), 2000), 7, mIn, 96, mIn, 64)

                if iszero(success) {
                    mstore(0, 0)
                    return(0, 0x20)
                }

                mstore(add(mIn, 64), mload(pR))
                mstore(add(mIn, 96), mload(add(pR, 32)))

                success := staticcall(sub(gas(), 2000), 6, mIn, 128, pR, 64)

                if iszero(success) {
                    mstore(0, 0)
                    return(0, 0x20)
                }
            }

            function checkPairing(pA, pB, pC, pubSignals, pMem) -> isOk {
                let _pPairing := add(pMem, pPairing)
                let _pVk := add(pMem, pVk)

                mstore(_pVk, IC0x)
                mstore(add(_pVk, 32), IC0y)

                // Compute the linear combination vk_x
                
                g1_mulAccC(_pVk, IC1x, IC1y, calldataload(add(pubSignals, 0)))
                
                g1_mulAccC(_pVk, IC2x, IC2y, calldataload(add(pubSignals, 32)))
                
                g1_mulAccC(_pVk, IC3x, IC3y, calldataload(add(pubSignals, 64)))
                
                g1_mulAccC(_pVk, IC4x, IC4y, calldataload(add(pubSignals, 96)))
                
                g1_mulAccC(_pVk, IC5x, IC5y, calldataload(add(pubSignals, 128)))
                
                g1_mulAccC(_pVk, IC6x, IC6y, calldataload(add(pubSignals, 160)))
                
                g1_mulAccC(_pVk, IC7x, IC7y, calldataload(add(pubSignals, 192)))
                
                g1_mulAccC(_pVk, IC8x, IC8y, calldataload(add(pubSignals, 224)))
                
                g1_mulAccC(_pVk, IC9x, IC9y, calldataload(add(pubSignals, 256)))
                
                g1_mulAccC(_pVk, IC10x, IC10y, calldataload(add(pubSignals, 288)))
                
                g1_mulAccC(_pVk, IC11x, IC11y, calldataload(add(pubSignals, 320)))
                

                // -A
                mstore(_pPairing, calldataload(pA))
                mstore(add(_pPairing, 32), mod(sub(q, calldataload(add(pA, 32))), q))

                // B
                mstore(add(_pPairing, 64), calldataload(pB))
                mstore(add(_pPairing, 96), calldataload(add(pB, 32)))
                mstore(add(_pPairing, 128), calldataload(add(pB, 64)))
                mstore(add(_pPairing, 160), calldataload(add(pB, 96)))

                // alpha1
                mstore(add(_pPairing, 192), alphax)
                mstore(add(_pPairing, 224), alphay)

                // beta2
                mstore(add(_pPairing, 256), betax1)
                mstore(add(_pPairing, 288), betax2)
                mstore(add(_pPairing, 320), betay1)
                mstore(add(_pPairing, 352), betay2)

                // vk_x
                mstore(add(_pPairing, 384), mload(add(pMem, pVk)))
                mstore(add(_pPairing, 416), mload(add(pMem, add(pVk, 32))))


                // gamma2
                mstore(add(_pPairing, 448), gammax1)
                mstore(add(_pPairing, 480), gammax2)
                mstore(add(_pPairing, 512), gammay1)
                mstore(add(_pPairing, 544), gammay2)

                // C
                mstore(add(_pPairing, 576), calldataload(pC))
                mstore(add(_pPairing, 608), calldataload(add(pC, 32)))

                // delta2
                mstore(add(_pPairing, 640), deltax1)
                mstore(add(_pPairing, 672), deltax2)
                mstore(add(_pPairing, 704), deltay1)
                mstore(add(_pPairing, 736), deltay2)


                let success := staticcall(sub(gas(), 2000), 8, _pPairing, 768, _pPairing, 0x20)

                isOk := and(success, mload(_pPairing))
            }

            let pMem := mload(0x40)
            mstore(0x40, add(pMem, pLastMem))

            // Validate that all evaluations ∈ F
            
            checkField(calldataload(add(_pubSignals, 0)))
            
            checkField(calldataload(add(_pubSignals, 32)))
            
            checkField(calldataload(add(_pubSignals, 64)))
            
            checkField(calldataload(add(_pubSignals, 96)))
            
            checkField(calldataload(add(_pubSignals, 128)))
            
            checkField(calldataload(add(_pubSignals, 160)))
            
            checkField(calldataload(add(_pubSignals, 192)))
            
            checkField(calldataload(add(_pubSignals, 224)))
            
            checkField(calldataload(add(_pubSignals, 256)))
            
            checkField(calldataload(add(_pubSignals, 288)))
            
            checkField(calldataload(add(_pubSignals, 320)))
            

            // Validate all evaluations
            let isValid := checkPairing(_pA, _pB, _pC, _pubSignals, pMem)

            mstore(0, isValid)
             return(0, 0x20)
         }
     }
 }
